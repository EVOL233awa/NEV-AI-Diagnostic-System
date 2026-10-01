"""本地小模型（可选，ornith-1.5-9b-mtp-iq4xs，llama-server :11435）：状态卡字段异步抽取 + 会话标题生成。

均在新会话首条描述后异步执行，不阻塞主对话；任一失败静默降级（状态卡留空/保留默认标题）。
模型矩阵定稿：抽取与标题走本地小模型，压缩走 DeepSeek 后台压缩模型。
"""
from __future__ import annotations

import json
import logging

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """从车主的车辆问题描述中抽取信息，输出 JSON 对象（没有的信息留空）：
{{"vehicle": "车型/年款/动力类型（描述里提到才填）",
  "symptoms": ["症状/现象"]}}

只输出 JSON，不要解释。

车主描述：{text}"""


async def extract_case_notes(text: str) -> dict | None:
    """调用本地小模型抽取状态卡初稿；不可用/失败/输出不合法一律返回 None。"""
    url = (settings.local_models.get("subagent_url") or "").rstrip("/")
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.post(
                f"{url}/chat/completions",
                json={
                    "model": "ornith-1.5-9b-mtp-iq4xs",
                    "messages": [{"role": "user", "content": EXTRACT_PROMPT.format(text=text[:800])}],
                    "max_tokens": 300,
                    "temperature": 0.0,  # 抽取求稳：贪心解码，消除 9B 漏抽抖动（实测 1/15 正例漏抽）
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"] or ""
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("本地小模型抽取不可用（状态卡留空降级）：%s", exc)
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


TITLE_PROMPT = """给下面的汽车诊断对话开头起一个简短标题，概括车主咨询的核心问题。

要求：口语化中文，不超过 12 个字，只输出标题本身，不要引号、标点结尾或任何解释。

对话开头：{text}"""

_TITLE_STRIP_CHARS = "《》\"'“”‘’·。.！!？?，,、；;：: \t\n\r"


async def generate_session_title(text: str) -> str | None:
    """调用本地小模型生成会话标题；不可用/失败/空输出返回 None（调用方保留默认标题）。"""
    url = (settings.local_models.get("subagent_url") or "").rstrip("/")
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.post(
                f"{url}/chat/completions",
                json={
                    "model": "ornith-1.5-9b-mtp-iq4xs",
                    "messages": [{"role": "user", "content": TITLE_PROMPT.format(text=text[:500])}],
                    "max_tokens": 60,
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"] or ""
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("本地小模型标题生成不可用（保留默认标题）：%s", exc)
        return None
    title = content.strip().strip(_TITLE_STRIP_CHARS)
    if not title:
        return None
    return title[:16]  # 12 字目标留 4 字符余量，硬截防模型超长（长度约束放代码层）
