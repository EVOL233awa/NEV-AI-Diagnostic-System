"""ASR provider 包：统一结果结构与注册入口。"""
from backend.core.providers.asr.base import ASRProvider, ASRResult, ASRUnavailable
from backend.core.providers.asr.registry import PROVIDER_NAMES, get_provider, is_available, provider_name

__all__ = [
    "ASRProvider",
    "ASRResult",
    "ASRUnavailable",
    "PROVIDER_NAMES",
    "get_provider",
    "is_available",
    "provider_name",
]
