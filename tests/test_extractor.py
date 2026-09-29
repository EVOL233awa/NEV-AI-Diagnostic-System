"""本地子代理抽取/标题生成的离线单测（B1）——httpx 全 mock，绝不触 :11435。

覆盖：JSON 剥取（纯/fence/噪声前后缀）、非法输出降级 None、字段清洗
（vehicle 截断、symptoms 过滤+上限）、URL 未配置降级、网络异常降级、
标题 strip 与 16 字硬截。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import backend.core.agent.extractor as extractor


class _FakeResp:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


class _FakeClient:
    """类属性 payload 换桩：str=正常响应；Exception=网络/协议异常。"""

    payload: str | Exception = ""

    def __init__(self, *args, **kwargs) -> None:
        return None

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, *args, **kwargs) -> _FakeResp:
        if isinstance(_FakeClient.payload, Exception):
            raise _FakeClient.payload
        return _FakeResp(_FakeClient.payload)


@pytest.fixture(autouse=True)
def fake_http(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        extractor,
        "httpx",
        SimpleNamespace(AsyncClient=_FakeClient, HTTPError=httpx.HTTPError),
    )
    monkeypatch.setattr(
        extractor,
        "settings",
        SimpleNamespace(local_models={"subagent_url": "http://fake:11435"}),
    )
    yield


def _run(text: str) -> dict | None:
    return asyncio.run(extractor.extract_case_notes(text))


def _title(text: str) -> str | None:
    return asyncio.run(extractor.generate_session_title(text))


class TestExtractCaseNotes:
    def test_plain_json(self):
        _FakeClient.payload = json.dumps(
            {"vehicle": "比亚迪 汉 EV 2023", "symptoms": ["高速发飘", "方向盘抖"]}, ensure_ascii=False
        )
        notes = _run("换了胎之后高速发飘")
        assert notes == {"vehicle": "比亚迪 汉 EV 2023", "symptoms": ["高速发飘", "方向盘抖"]}

    def test_json_fence_and_noise(self):
        body = json.dumps({"vehicle": "特斯拉 M3", "symptoms": ["充电慢"]}, ensure_ascii=False)
        _FakeClient.payload = f"好的，以下是抽取结果：\n```json\n{body}\n```\n请查收。"
        notes = _run("充电慢")
        assert notes == {"vehicle": "特斯拉 M3", "symptoms": ["充电慢"]}

    @pytest.mark.parametrize("bad", ["", "   ", "我不会回答这个问题", "[1,2,3]", "{broken"])
    def test_invalid_output_returns_none(self, bad: str):
        _FakeClient.payload = bad
        assert _run("随便描述") is None

    def test_field_sanitizing(self):
        _FakeClient.payload = json.dumps(
            {
                "vehicle": "v" * 100,
                "symptoms": ["a", "  ", 123, "b", "c", "d", "e", "f"],
                "extra": "ignored",
            },
            ensure_ascii=False,
        )
        notes = _run("x")
        assert notes["vehicle"] == "v" * 64
        assert notes["symptoms"] == ["a", "b", "c", "d", "e"]  # 空串/非字符串过滤 + 上限 5

    def test_no_url_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(extractor, "settings", SimpleNamespace(local_models={}))
        assert _run("x") is None

    def test_network_error_returns_none(self):
        _FakeClient.payload = httpx.ConnectError("refused")
        assert _run("x") is None

    def test_empty_dict_returns_none(self):
        _FakeClient.payload = "{}"
        assert _run("x") is None


class TestGenerateSessionTitle:
    def test_plain(self):
        _FakeClient.payload = "冬天续航掉电快"
        assert _title("冬天续航掉得厉害") == "冬天续航掉电快"

    def test_strip_quotes_and_punct(self):
        _FakeClient.payload = '《充电跳枪是怎么回事》。！'
        assert _title("x") == "充电跳枪是怎么回事"

    def test_hard_truncate_16(self):
        _FakeClient.payload = "这个标题实在是太长了远远超过十六个字的限制需要硬截断处理"
        assert _title("x") == "这个标题实在是太长了远远超过十六个字"[:16]
        assert len(_title("x")) == 16

    def test_empty_returns_none(self):
        _FakeClient.payload = "   "
        assert _title("x") is None

    def test_network_error_returns_none(self):
        _FakeClient.payload = httpx.ReadTimeout("timeout")
        assert _title("x") is None
