"""DeepSeek 官方语音识别适配器。

接口：POST {base_url}/v1/tools/asr（multipart 字段 file）
- 仅接受 16-bit PCM WAV 或 Ogg Opus；上传前校验 magic bytes，不通过由 API 层转 415。
- 专用 api_key 为空时，仅当 base_url 指向 api.deepseek.com 才回退主模型 key。
- 不重试、不落盘、不记录识别文本。
"""
from __future__ import annotations

import httpx

from backend.config import is_official_deepseek, settings
from backend.core.providers.asr.base import ASRResult, ASRUnavailable


def _endpoint(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"


def is_supported_audio(audio: bytes) -> bool:
    return audio[:4] == b"OggS" or (audio[:4] == b"RIFF" and audio[8:12] == b"WAVE")


class DeepSeekASR:
    name = "deepseek"

    def _cfg(self) -> dict:
        cfg = settings.asr.get("deepseek")
        return cfg if isinstance(cfg, dict) else {}

    def _base_url(self) -> str:
        return str(self._cfg().get("base_url") or "").rstrip("/")

    def api_key(self) -> str:
        key = str(self._cfg().get("api_key") or "").strip()
        if key:
            return key
        if is_official_deepseek(self._base_url()):
            return str(settings.deepseek.get("main_key") or "")
        return ""

    def is_configured(self) -> bool:
        return bool(self._base_url() and self.api_key())

    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> ASRResult:
        if not self.is_configured():
            raise ASRUnavailable("DeepSeek 语音识别未配置（base_url/api_key）", code="not_configured")
        if not is_supported_audio(audio):
            raise ASRUnavailable("DeepSeek 语音识别仅支持 16-bit PCM WAV 或 Ogg Opus", code="unsupported_format")
        cfg = self._cfg()
        timeout = float(cfg.get("timeout") or 60)
        files = {"file": (filename or "audio.wav", audio, content_type or "application/octet-stream")}
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(
                    _endpoint(self._base_url(), "/tools/asr"),
                    files=files,
                    headers={"Authorization": f"Bearer {self.api_key()}"},
                )
        except httpx.TimeoutException as exc:
            raise ASRUnavailable("语音识别上传超时（HTTP 408）", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise ASRUnavailable(f"语音识别连接失败：{exc}", code="network") from exc

        if resp.status_code in (401, 403):
            raise ASRUnavailable(f"DeepSeek 语音识别 key 无效或无权限（HTTP {resp.status_code}）", code="auth")
        if resp.status_code == 408:
            raise ASRUnavailable("语音识别上传超时（HTTP 408）", code="timeout")
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
            data = resp.json()
        except ValueError as exc:
            raise ASRUnavailable("语音识别响应不是合法 JSON", code="protocol") from exc

        text = str(data.get("text") or "")
        try:
            duration_ms = int(data.get("duration_ms") or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        request_id = data.get("request_id")
        return ASRResult(
            text=text,
            duration_ms=duration_ms,
            provider=self.name,
            request_id=str(request_id) if request_id else None,
        )
