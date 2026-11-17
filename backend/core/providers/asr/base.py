"""ASR provider 公共契约：统一结果结构与异常。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ASRResult:
    text: str
    duration_ms: int
    provider: str
    request_id: str | None


class ASRUnavailable(RuntimeError):
    """语音识别不可用；code 供 API 层映射 HTTP 状态与可读文案。"""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class ASRProvider(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    async def transcribe(self, audio: bytes, filename: str, content_type: str) -> ASRResult: ...
