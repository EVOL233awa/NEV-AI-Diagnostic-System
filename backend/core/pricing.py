"""外部能力单价常量与成本折算（单位统一 CNY）。

供应商标价以 USD 计：搜索 $0.75 / 1000 次成功请求、ASR $0.116 / 音频小时
（DeepSeek 官方限时价 $0.058/小时）。按固定估算汇率 USD_TO_CNY 折算为人民币，
仅用于用量展示与预算判断，不参与任何结算。
主模型 token 成本无法可靠估算，保持 None、不参与全局预算；全局预算只覆盖搜索/ASR。
"""
from __future__ import annotations

# 估算用固定汇率：仅把供应商标价折成人民币展示，不跟随实时汇率，也不用于结算
USD_TO_CNY = 7.2

SEARCH_COST_PER_CALL_USD = 0.00075
ASR_COST_PER_AUDIO_HOUR_USD = 0.116


def search_cost_cny() -> float:
    return round(SEARCH_COST_PER_CALL_USD * USD_TO_CNY, 8)


def asr_cost_cny(duration_ms: int) -> float:
    return round(max(duration_ms, 0) / 3_600_000 * ASR_COST_PER_AUDIO_HOUR_USD * USD_TO_CNY, 8)
