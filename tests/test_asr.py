"""ASR 接口与 provider 测试：角色、大小/时长、错误映射、限额、usage/审计、key 回退。

provider 与 HTTP 全部 mock，绝不调用真实语音识别服务。
"""
from __future__ import annotations

import asyncio
import struct
from types import SimpleNamespace

import httpx
import pytest

import backend.api.asr as asr_api
import backend.core.providers.asr.deepseek as ds_asr
import backend.core.providers.asr.openai_compat as oa_asr
import backend.core.quota as quota_mod
from backend.core.providers.asr.base import ASRResult, ASRUnavailable
from backend.db.models import AuditLog, UsageStat, User
from backend.seed.seed import SUPERADMIN_ENV_VAR, reset_superadmin_password

WAV_HEADER = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"data" + b"\x00" * 32


def _pcm_wav(seconds: float, rate: int = 16000) -> bytes:
    """标准 16-bit PCM mono WAV，用于验证服务端独立解析时长。"""
    data = b"\x00\x00" * int(rate * seconds)
    fmt = struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return (
        b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data)) + b"WAVE"
        + b"fmt " + fmt
        + b"data" + struct.pack("<I", len(data)) + data
    )


class _StubProvider:
    name = "deepseek"

    def __init__(self) -> None:
        self.text = "空调不制冷"
        self.error: Exception | None = None
        self.configured = True
        self.received: bytes | None = None
        self.duration_ms = 3000

    def is_configured(self) -> bool:
        return self.configured

    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> ASRResult:
        self.received = audio
        if self.error is not None:
            raise self.error
        return ASRResult(text=self.text, duration_ms=self.duration_ms, provider=self.name, request_id="req-1")


@pytest.fixture
def stub_provider(monkeypatch):
    stub = _StubProvider()
    monkeypatch.setattr(asr_api, "get_provider", lambda: stub)
    return stub


@pytest.fixture
def superadmin_headers(client, monkeypatch):
    monkeypatch.delenv(SUPERADMIN_ENV_VAR, raising=False)
    password = reset_superadmin_password()
    r = client.post("/api/auth/login", json={"username": "superadmin", "password": password})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _post(client, headers, audio: bytes = WAV_HEADER, duration_ms: str | None = "3000"):
    data = {"duration_ms": duration_ms} if duration_ms is not None else None
    return client.post(
        "/api/asr/transcribe",
        headers=headers,
        files={"file": ("voice.wav", audio, "audio/wav")},
        data=data,
    )


class TestAccess:
    def test_anonymous_rejected(self, client):
        assert _post(client, {}).status_code == 401

    def test_superadmin_forbidden(self, client, superadmin_headers):
        assert _post(client, superadmin_headers).status_code == 403

    @pytest.mark.parametrize("role_headers", ["owner_headers", "staff_headers", "admin_headers"])
    def test_roles_allowed(self, client, role_headers, stub_provider, request):
        headers = request.getfixturevalue(role_headers)
        r = _post(client, headers)
        assert r.status_code == 200
        assert r.json()["text"] == "空调不制冷"
        assert r.json()["provider"] == "deepseek"


class TestValidation:
    def test_empty_audio(self, client, owner_headers, stub_provider):
        assert _post(client, owner_headers, audio=b"").status_code == 400

    def test_too_large(self, client, owner_headers, stub_provider, monkeypatch):
        monkeypatch.setitem(asr_api.settings.raw.setdefault("asr", {}), "max_bytes", 16)
        assert _post(client, owner_headers, audio=b"x" * 17).status_code == 413

    def test_duration_over_limit(self, client, owner_headers, stub_provider, monkeypatch):
        monkeypatch.setitem(asr_api.settings.raw.setdefault("asr", {}), "max_seconds", 10)
        assert _post(client, owner_headers, duration_ms="11000").status_code == 400

    def test_unknown_audio_format_rejected(self, client, owner_headers, stub_provider):
        assert _post(client, owner_headers, audio=b"not-audio" * 10).status_code == 415

    def test_server_derives_wav_duration_when_provider_returns_zero(
        self, client, owner_headers, stub_provider
    ):
        stub_provider.duration_ms = 0
        r = _post(client, owner_headers, audio=_pcm_wav(1.0), duration_ms=None)
        assert r.status_code == 200, r.text
        assert 995 <= r.json()["duration_ms"] <= 1005

    def test_duration_uses_max_of_client_and_server(
        self, client, owner_headers, stub_provider
    ):
        stub_provider.duration_ms = 0
        r = _post(client, owner_headers, audio=_pcm_wav(2.0), duration_ms="100")
        assert r.status_code == 200, r.text
        assert 1995 <= r.json()["duration_ms"] <= 2005

    def test_unknown_duration_rejected(self, client, owner_headers, stub_provider):
        stub_provider.duration_ms = 0
        r = _post(client, owner_headers, audio=WAV_HEADER, duration_ms=None)
        assert r.status_code == 400 and "无法确定录音时长" in r.json()["detail"]

    def test_not_configured(self, client, owner_headers, stub_provider):
        stub_provider.configured = False
        r = _post(client, owner_headers)
        assert r.status_code == 503 and "未配置" in r.json()["detail"]

    @pytest.mark.parametrize(
        "code,expected", [("unsupported_format", 415), ("too_large", 413),
                          ("rate_limit", 429), ("busy", 503), ("timeout", 504)],
    )
    def test_provider_error_mapping(self, client, owner_headers, stub_provider, code, expected):
        stub_provider.error = ASRUnavailable("上游错误", code=code)
        assert _post(client, owner_headers).status_code == expected


class TestUsageAndQuota:
    def test_usage_and_audit_written_without_text(self, client, db_session, owner_headers, stub_provider):
        owner = db_session.query(User).filter(User.username == "user001").one()
        before = db_session.query(UsageStat).filter_by(slot="asr", user_id=owner.id).count()
        r = _post(client, owner_headers)
        assert r.status_code == 200
        db_session.expire_all()
        rows = (db_session.query(UsageStat)
                .filter_by(slot="asr", user_id=owner.id)
                .order_by(UsageStat.id.desc()).all())
        assert len(rows) == before + 1
        assert rows[0].duration_ms == 3000
        assert rows[0].cost_estimate and rows[0].cost_estimate > 0
        audit = (db_session.query(AuditLog)
                 .filter_by(action="asr_transcribe", user_id=owner.id)
                 .order_by(AuditLog.id.desc()).first())
        assert audit is not None
        assert "text" not in audit.detail
        assert "空调不制冷" not in str(audit.detail)

    def test_per_user_quota(self, client, db_session, owner_headers, stub_provider, monkeypatch):
        owner = db_session.query(User).filter(User.username == "user001").one()
        db_session.add(UsageStat(tenant_id=1, user_id=owner.id, slot="asr", duration_ms=120_000))
        db_session.commit()
        monkeypatch.setattr(quota_mod, "settings", SimpleNamespace(quota={
            "asr_daily_seconds_per_user": 60,
            "search_daily_calls_per_user": None,
            "global_daily_usd": None,
        }))
        r = _post(client, owner_headers)
        assert r.status_code == 429 and "额度已用完" in r.json()["detail"]
        db_session.expire_all()
        audit = (db_session.query(AuditLog)
                 .filter_by(action="asr_transcribe", user_id=owner.id)
                 .order_by(AuditLog.id.desc()).first())
        assert audit is not None and audit.detail["blocked"] == "user"

    def test_global_budget(self, client, db_session, owner_headers, stub_provider, monkeypatch):
        db_session.add(UsageStat(tenant_id=1, user_id=999, slot="search", cost_estimate=5.0))
        db_session.commit()
        monkeypatch.setattr(quota_mod, "settings", SimpleNamespace(quota={
            "asr_daily_seconds_per_user": None,
            "search_daily_calls_per_user": None,
            "global_daily_usd": 1.0,
        }))
        r = _post(client, owner_headers)
        assert r.status_code == 503 and "预算已用完" in r.json()["detail"]


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    response: _FakeResponse = _FakeResponse()
    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        return None

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url: str, **kwargs) -> _FakeResponse:
        _FakeClient.calls.append({"url": url, **kwargs})
        return _FakeClient.response


def _patch_http(monkeypatch, module):
    monkeypatch.setattr(module, "httpx", SimpleNamespace(
        AsyncClient=_FakeClient, HTTPError=httpx.HTTPError, TimeoutException=httpx.TimeoutException,
    ))
    _FakeClient.calls = []
    _FakeClient.response = _FakeResponse()


class TestDeepSeekProvider:
    def _settings(self, base: str = "https://api.deepseek.com", key: str = "sk-asr"):
        return SimpleNamespace(
            asr={"deepseek": {"base_url": base, "api_key": key, "timeout": 5}},
            deepseek={"main_key": "sk-main"},
        )

    def test_magic_bytes_and_key_fallback(self, monkeypatch):
        monkeypatch.setattr(ds_asr, "settings", self._settings(key=""))
        provider = ds_asr.DeepSeekASR()
        assert provider.is_configured() and provider.api_key() == "sk-main"
        with pytest.raises(ASRUnavailable) as info:
            asyncio.run(provider.transcribe(b"not-audio", "a.wav", "audio/wav"))
        assert info.value.code == "unsupported_format"

        monkeypatch.setattr(ds_asr, "settings", self._settings(base="https://api.other.com", key=""))
        assert not ds_asr.DeepSeekASR().is_configured()

    def test_success_mapping(self, monkeypatch):
        monkeypatch.setattr(ds_asr, "settings", self._settings())
        _patch_http(monkeypatch, ds_asr)
        _FakeClient.response = _FakeResponse(200, {"text": "你好", "duration_ms": 2500, "request_id": "r1"})
        result = asyncio.run(ds_asr.DeepSeekASR().transcribe(WAV_HEADER, "voice.wav", "audio/wav"))
        assert result.text == "你好" and result.duration_ms == 2500 and result.request_id == "r1"
        assert _FakeClient.calls[0]["url"] == "https://api.deepseek.com/v1/tools/asr"

    @pytest.mark.parametrize("status,expected", [(400, "format"), (408, "timeout"),
                                                 (413, "too_large"), (429, "rate_limit"),
                                                 (503, "busy")])
    def test_error_mapping(self, monkeypatch, status, expected):
        monkeypatch.setattr(ds_asr, "settings", self._settings())
        _patch_http(monkeypatch, ds_asr)
        _FakeClient.response = _FakeResponse(status)
        with pytest.raises(ASRUnavailable) as info:
            asyncio.run(ds_asr.DeepSeekASR().transcribe(WAV_HEADER, "voice.wav", "audio/wav"))
        assert info.value.code in expected or expected in info.value.code


class TestOpenAIProvider:
    def test_request_and_mapping(self, monkeypatch):
        monkeypatch.setattr(oa_asr, "settings", SimpleNamespace(asr={"openai": {
            "base_url": "https://asr.example.com", "api_key": "oa-key",
            "model": "whisper-1", "timeout": 5,
        }}))
        _patch_http(monkeypatch, oa_asr)
        _FakeClient.response = _FakeResponse(200, {"text": "识别结果"})
        result = asyncio.run(oa_asr.OpenAICompatASR().transcribe(b"\x00" * 64, "voice.webm", "audio/webm"))
        assert result.text == "识别结果" and result.duration_ms == 0
        call = _FakeClient.calls[0]
        assert call["url"] == "https://asr.example.com/v1/audio/transcriptions"
        assert call["data"]["model"] == "whisper-1"
        assert call["headers"]["Authorization"] == "Bearer oa-key"
