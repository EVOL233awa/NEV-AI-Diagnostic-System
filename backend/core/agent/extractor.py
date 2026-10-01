"""标题/状态卡抽取的小模型客户端（异步，不阻塞主对话；失败静默降级）。

槽位链：small_model 节（base_url+model 配置齐全时直连，OpenAI 兼容 API，如硅基流动
Qwen3.5-4B 免费档）→ 缺省回退 background 槽位（主聊天模型，deepseek-flash 实测
disable_thinking 后 P50 约 560ms）。

2026-10-02 实测：硅基流动 Qwen3.5-4B 免费档排队严重（尾部 59-90s），不作默认；
deepseek-flash 关思考 559ms/6 token，标题质量与本地 ornith 相当，故默认走 background。
参数（温度/max_tokens/输入截断）全部在 small_model 节配置化，superadmin 在线可调。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from backend.config import settings
from backend.core.providers.llm import get_background_provider

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

# 云端小模型请求超时：留足排队余量（免费档实测尾部可达数十秒，超时即静默降级）
_REQUEST_TIMEOUT_S = 30.0


def _sm_config(key: str, default: Any) -> Any:
    return settings.small_model.get(key, default)


async def _call_small_model(prompt: str, *, max_tokens: int, temperature: float) -> str:
    """小模型槽位优先，缺省回退 background 槽位；返回 content（失败抛异常）。"""
    if _sm_config("disable_thinking", True):
        extra: dict[str, Any] = {"thinking": {"type": "disabled"}}
    else:
        extra = {}
    base_url = str(_sm_config("base_url", "") or "").strip()
    model = str(_sm_config("model", "") or "").strip()
    if base_url and model:
        headers = {"Content-Type": "application/json"}
        api_key = str(_sm_config("api_key", "") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            **extra,
        }
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S, trust_env=False) as client:
            resp = await client.post(f"{base_url.rstrip('/')}/chat/completions", json=body, headers=headers)
            resp.raise_for_status()
            return str(resp.json()["choices"][0]["message"]["content"] or "")
    # 回退：主聊天模型（background 槽位，独立 Key 不挤占前台限速配额）
    result = await get_background_provider().chat(
        [{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=temperature, **extra
    )
    return result.content


async def extract_case_notes(text: str) -> dict | None:
    """调用小模型抽取状态卡初稿；不可用/失败/输出不合法一律返回 None。"""
    try:
        content = await _call_small_model(
            EXTRACT_PROMPT.format(text=text[: int(_sm_config("extract_input_chars", 800))]),
            max_tokens=int(_sm_config("extract_max_tokens", 300)),
            temperature=float(_sm_config("extract_temperature", 0.0)),
        )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("小模型抽取不可用（状态卡留空降级）：%s", exc)
        return None

    # 小模型习惯带 ```json fence 或前后缀，剥出首个 {...} 平衡块再解析
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
    """调用小模型生成会话标题；不可用/失败/空输出返回 None（调用方保留默认标题）。"""
    try:
        content = await _call_small_model(
            TITLE_PROMPT.format(text=text[: int(_sm_config("title_input_chars", 500))]),
            max_tokens=int(_sm_config("title_max_tokens", 60)),
            temperature=float(_sm_config("title_temperature", 0.2)),
        )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("小模型标题生成不可用（保留默认标题）：%s", exc)
        return None
    title = content.strip().strip(_TITLE_STRIP_CHARS)
    if not title:
        return None
    return title[:16]  # 12 字目标留 4 字符余量，硬截防模型超长（长度约束放代码层）
