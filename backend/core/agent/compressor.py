"""上下文压缩（§5 AstrBot 双阀门）。

阀门 1 轮数截断：超过 max_rounds 轮的最早轮次不进模型上下文。
阀门 2 token 阈值：估算超预算 → 压缩模型把更早轮次摘要成"前情摘要"（独立槽位 Key）。

参数（compress_max_rounds / compress_token_budget / compress_min_keep_rounds /
summary_max_chars）实时读 config.json agent 节（superadmin 后台在线可调，
缺省见 config.AGENT_DEFAULTS），改完即对后续轮次生效。

持久化与降级约定：
- 前情摘要存 sessions.context_summary，已压缩边界存 sessions.summarized_until_id
  （messages 表原文保留，只是不再进上下文，回看/审计不受影响）。
- 压缩模型不可用或失败 → 降级为纯轮数截断（边界同样前移，避免每轮重复失败调用）。
- 诊断状态卡（session.case_notes）独立持久化：压缩丢的是对话原文，不丢诊断事实。
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session as DbSession

from backend.config import agent_param
from backend.core.providers.llm import get_background_provider, provider_label
from backend.db.models import Session as ChatSession

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """你是会话压缩器。把下面的诊断对话历史压缩成一份"前情摘要"，供后续诊断延续使用。

要求：
1. 保留诊断事实：车辆信息、车主已确认的症状与回答、已给出的结论与严重度、已排除或存疑的假设、待确认事项。
2. 丢弃寒暄、重复检索原文、可从知识库重新查到的细节；检索结论保留"查到了什么"一句话即可。
3. 用紧凑的条目化中文输出，不超过 {max_chars} 字，不要添加评论。

{old_text}"""


def estimate_tokens(messages: list[dict]) -> int:
    """粗估 token：中英混合按 1.6 字符/token，另加每条消息固定开销。"""
    chars = sum(len(str(m.get("content") or "")) for m in messages)
    return int(chars / 1.6) + len(messages) * 4


def _split_rounds(history: list[dict]) -> list[list[dict]]:
    """OpenAI 消息序列 → 按轮分组：一条 user 开启一轮，其后 assistant/tool 归入同轮。"""
    rounds: list[list[dict]] = []
    for m in history:
        if m["role"] == "user" or not rounds:
            rounds.append([m])
        else:
            rounds[-1].append(m)
    return rounds


def _old_text(old: list[dict], prev_summary: str) -> str:
    lines = []
    if prev_summary:
        lines.append(f"（此前已有的前情摘要：\n{prev_summary}\n）")
    for m in old:
        role = m["role"]
        content = str(m.get("content") or "")
        if role == "tool":
            lines.append(f"[工具结果] {content[:300]}")
        elif role == "assistant" and m.get("tool_calls"):
            names = ",".join(c.get("function", {}).get("name", "?") for c in m["tool_calls"])
            extra = f"（调用工具：{names}）" if content else ""
            lines.append(f"[助手] {content[:300]}{extra}")
        else:
            lines.append(f"[{'车主' if role == 'user' else '助手'}] {content[:400]}")
    return "\n".join(lines) if lines else "（无）"


async def _summarize(old: list[dict], prev_summary: str, db: DbSession, session: ChatSession) -> str | None:
    """调后台压缩槽位生成摘要；失败返回 None（调用方降级为纯截断）。usage 落账 slot=compression。"""
    provider = get_background_provider()
    if not provider.api_key:
        return None
    max_chars = int(agent_param("summary_max_chars"))
    prompt = SUMMARY_PROMPT.format(max_chars=max_chars, old_text=_old_text(old, prev_summary))
    try:
        result = await provider.chat(
            [
                {"role": "system", "content": "你是诊断会话压缩器，只输出摘要本身。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1000,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001  压缩失败不阻断主链路
        logger.warning("上下文压缩调用失败（降级为截断）：%s", exc)
        return None
    if result.usage:
        from backend.db.models import UsageStat

        db.add(
            UsageStat(
                tenant_id=session.tenant_id,
                user_id=session.user_id,
                slot="compression",
                provider=provider_label(provider.base_url),
                model=provider.model,
                tokens_in=int(result.usage.get("prompt_tokens", 0)),
                tokens_out=int(result.usage.get("completion_tokens", 0)),
                latency_ms=0,
            )
        )
    text = result.content.strip()
    return text[:max_chars] if text else None


def _strip_internal(history: list[dict]) -> list[dict]:
    """剥掉 build_history 附带的 _id 内部键，得到可发送的 OpenAI 消息。"""
    return [{k: v for k, v in m.items() if not k.startswith("_")} for m in history]


async def maybe_compress(db: DbSession, session: ChatSession, history: list[dict]) -> list[dict]:
    """双阀门入口：输入 build_history 全量序列（dict 带 _id），返回裁剪+摘要注入后的可发送序列。

    - 已有压缩边界：边界之前的消息不再重复参与裁剪（其内容已概括在 context_summary）。
    - 阀门 1 超轮 / 阀门 2 超 token → 截出 old 段；摘要成功则更新 session 并注入摘要消息，
      失败则静默前移边界（降级为截断）。
    """
    boundary = session.summarized_until_id or 0
    compressed_part = [m for m in history if (m.get("_id") or 0) <= boundary]
    eligible = [m for m in history if (m.get("_id") or 0) > boundary]

    max_rounds = int(agent_param("compress_max_rounds"))
    token_budget = int(agent_param("compress_token_budget"))
    min_keep_rounds = int(agent_param("compress_min_keep_rounds"))

    # 阀门 1：轮数截断
    rounds = _split_rounds(eligible)
    overflow: list[dict] = []
    if len(rounds) > max_rounds:
        overflow = [m for r in rounds[:-max_rounds] for m in r]
        eligible = [m for r in rounds[-max_rounds:] for m in r]

    # 阀门 2：token 预算（从保留段前部再截，最少留 min_keep_rounds 轮）
    kept = compressed_part + eligible
    if estimate_tokens(kept) > token_budget:
        kept_rounds = _split_rounds(kept)
        if len(kept_rounds) > min_keep_rounds:
            cut = max(1, len(kept_rounds) // 2)
            overflow = overflow + [m for r in kept_rounds[:cut] for m in r]
            kept = [m for r in kept_rounds[cut:] for m in r]

    if not overflow:
        if boundary and session.context_summary:
            # 已有压缩边界且本轮未新增压缩：已压缩原文继续用摘要替代，不回流
            return _strip_internal(
                [{"role": "system",
                  "content": f"[前情摘要]（更早对话已压缩，事实如下）\n{session.context_summary}"},
                 *eligible]
            )
        return _strip_internal(history)

    prev_summary = session.context_summary or ""
    summary = await _summarize(overflow, prev_summary, db, session)
    last_id = max((m.get("_id") or 0) for m in overflow)
    if summary:
        session.context_summary = summary
        session.summarized_until_id = last_id
        db.commit()
        return _strip_internal(
            [{"role": "system", "content": f"[前情摘要]（更早对话已压缩，事实如下）\n{summary}"},
             *kept]
        )

    # 降级：纯截断，边界照样前移避免重复失败调用
    kept = [m for m in kept if (m.get("_id") or 0) > last_id]
    session.summarized_until_id = last_id
    db.commit()
    return _strip_internal(kept)
