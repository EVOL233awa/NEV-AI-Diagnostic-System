"""OpenAI 兼容语音转写适配器（自定义 ASR 接口落点）。

接口：POST {base_url}/v1/audio/transcriptions（multipart：file、model）
允许 webm/mp3/m4a/wav/ogg；响应只需 {"text"}，无 duration_ms 时由 API 层用前端上报值。
"""
from __future__ import annotations

import httpx

from backend.config import settings
from backend.core.providers.asr.base import ASRResult, ASRUnavailable


def _endpoint(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"


class OpenAICompatASR:
    name = "openai"

    def _cfg(self) -> dict:
        cfg = settings.asr.get("openai")
        return cfg if isinstance(cfg, dict) else {}

    def _base_url(self) -> str:
        return str(self._cfg().get("base_url") or "").rstrip("/")

    def api_key(self) -> str:
        return str(self._cfg().get("api_key") or "").strip()

    def is_configured(self) -> bool:
        return bool(self._base_url() and self._cfg().get("model"))

    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> ASRResult:
        if not self.is_configured():
            raise ASRUnavailable("OpenAI 兼容语音识别未配置（base_url/model）", code="not_configured")
        cfg = self._cfg()
        timeout = float(cfg.get("timeout") or 60)
        data = {"model": str(cfg.get("model") or "")}
        files = {"file": (filename or "audio.webm", audio, content_type or "application/octet-stream")}
        headers = {"Authorization": f"Bearer {self.api_key()}"} if self.api_key() else {}
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(
                    _endpoint(self._base_url(), "/audio/transcriptions"),
                    data=data, files=files, headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise ASRUnavailable("语音识别请求超时", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise ASRUnavailable(f"语音识别连接失败：{exc}", code="network") from exc

        if resp.status_code in (401, 403):
            raise ASRUnavailable(f"语音识别 key 无效或无权限（HTTP {resp.status_code}）", code="auth")
        if resp.status_code == 413:
            raise ASRUnavailable("音频超过服务端大小限制（HTTP 413）", code="too_large")
        if resp.status_code == 429:
            raise ASRUnavailable("语音识别请求过多（HTTP 429）", code="rate_limit")
        if resp.status_code == 400:
            raise ASRUnavailable("音频格式不支持或参数错误（HTTP 400）", code="bad_format")
        if resp.status_code in (503, 504):
            raise ASRUnavailable(f"语音识别服务繁忙或超时（HTTP {resp.status_code}）", code="busy")
        if resp.status_code >= 500:
            raise ASRUnavailable(f"语音识别服务异常（HTTP {resp.status_code}）", code="server")
        if resp.status_code >= 400:
            raise ASRUnavailable(f"语音识别请求失败（HTTP {resp.status_code}）", code="bad_request")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ASRUnavailable("语音识别响应不是合法 JSON", code="protocol") from exc
        return ASRResult(
            text=str(payload.get("text") or ""),
            duration_ms=0,
            provider=self.name,
            request_id=str(payload["request_id"]) if payload.get("request_id") else None,
        )
