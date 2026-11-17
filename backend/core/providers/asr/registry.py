"""ASR provider 注册表：按配置选择 deepseek / openai 兼容实现。"""
from __future__ import annotations

from backend.config import settings
from backend.core.providers.asr.base import ASRProvider, ASRUnavailable
from backend.core.providers.asr.deepseek import DeepSeekASR
from backend.core.providers.asr.openai_compat import OpenAICompatASR

PROVIDER_NAMES = ("deepseek", "openai")


def get_provider(name: str | None = None) -> ASRProvider:
    selected = (name or str(settings.asr.get("provider") or "deepseek")).strip().lower()
    if selected == "deepseek":
        return DeepSeekASR()
    if selected == "openai":
        return OpenAICompatASR()
    raise ASRUnavailable(f"未知语音识别 provider：{selected}", code="bad_config")


def provider_name() -> str:
    return str(settings.asr.get("provider") or "deepseek").strip().lower()


def is_available(name: str | None = None) -> bool:
    try:
        return get_provider(name).is_configured()
    except ASRUnavailable:
        return False
