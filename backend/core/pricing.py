"""外部能力单价常量与成本折算（单位统一 USD）。

搜索：$0.75 / 1000 次成功请求 → $0.00075/次。
ASR：$0.116 / 音频小时（DeepSeek 官方限时价 $0.058/小时）。
主模型 token 成本无法可靠估算，保持 None、不参与全局预算；全局预算只覆盖搜索/ASR。
"""
from __future__ import annotations

SEARCH_COST_PER_CALL_USD = 0.00075
ASR_COST_PER_AUDIO_HOUR_USD = 0.116


def search_cost_usd() -> float:
    return SEARCH_COST_PER_CALL_USD


def asr_cost_usd(duration_ms: int) -> float:
    return round(max(duration_ms, 0) / 3_600_000 * ASR_COST_PER_AUDIO_HOUR_USD, 8)
