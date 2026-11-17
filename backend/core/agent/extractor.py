"""标题/状态卡抽取（异步，不阻塞主对话；失败静默降级）。

v2.1.0 三模型收敛后不再有独立小模型槽位：压缩、标题、抽取全部走主模型
（`get_aux_provider()`），辅助任务可用独立 aux_key 避免与主对话抢限流。
请求固定关闭思考（DeepSeek 的 thinking={"type":"disabled"}，其他供应商忽略该字段）；
参数（温度/max_tokens/输入截断）在 config.json agent 节配置化，superadmin 在线可调。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from backend.config import agent_param
from backend.core.providers.llm import get_aux_provider

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """从车主的车辆问题描述中抽取信息，输出 JSON 对象（没有的信息留空）：
{{"vehicle": "车型/年款/动力类型（描述里提到才填）",
  "symptoms": ["症状/现象"]}}

只输出 JSON，不要解释。

车主描述：{text}"""

TITLE_PROMPT = """给下面的汽车诊断对话开头起一个简短标题，概括车主咨询的核心问题。

要求：口语化中文，不超过 12 个字，只输出标题本身，不要引号、标点结尾或任何解释。

对话开头：{text}"""

_TITLE_STRIP_CHARS = "《》\"'“”‘’·。.！!？?，,、；;：: \t\n\r"

# 辅助任务统一关闭思考，压缩标题/抽取的输出预算（供应商不支持该字段时忽略）
_THINKING_DISABLED: dict[str, Any] = {"thinking": {"type": "disabled"}}


async def _call_aux_model(prompt: str, *, max_tokens: int, temperature: float) -> str:
    """调主模型（辅助 key 优先）；返回 content（失败抛异常）。"""
    result = await get_aux_provider().chat(
        [{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
        **_THINKING_DISABLED,
    )
    return result.content


async def extract_case_notes(text: str) -> dict | None:
    """抽取状态卡初稿；不可用/失败/输出不合法一律返回 None。"""
    try:
        content = await _call_aux_model(
            EXTRACT_PROMPT.format(text=text[: int(agent_param("extract_input_chars"))]),
            max_tokens=int(agent_param("extract_max_tokens")),
            temperature=float(agent_param("extract_temperature")),
        )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("辅助模型抽取不可用（状态卡留空降级）：%s", exc)
        return None

    # 模型习惯带 ```json fence 或前后缀，剥出首个 {...} 平衡块再解析
    content = content.strip()
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    end = -1
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    notes: dict = {}
    if isinstance(data.get("vehicle"), str) and data["vehicle"].strip():
        notes["vehicle"] = data["vehicle"].strip()[:64]
    symptoms = data.get("symptoms")
    if isinstance(symptoms, list):
        cleaned = [s.strip()[:64] for s in symptoms if isinstance(s, str) and s.strip()]
        if cleaned:
            notes["symptoms"] = cleaned[:5]
    return notes or None


async def generate_session_title(text: str) -> str | None:
    """生成会话标题；不可用/失败/空输出返回 None（调用方保留默认标题）。"""
    try:
        content = await _call_aux_model(
            TITLE_PROMPT.format(text=text[: int(agent_param("title_input_chars"))]),
            max_tokens=int(agent_param("title_max_tokens")),
            temperature=float(agent_param("title_temperature")),
        )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("辅助模型标题生成不可用（保留默认标题）：%s", exc)
        return None
    title = content.strip().strip(_TITLE_STRIP_CHARS)
    if not title:
        return None
    return title[:16]  # 12 字目标留 4 字符余量，硬截防模型超长（长度约束放代码层）
