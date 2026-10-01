"""Agentic 循环编排。

流程：系统提示词（触发策略+当前日期+无证据不下结论）→ 主模型流式输出 →
tool_calls 执行回填 → 循环（安全阀：工具调用 ≤max_tool_rounds 次/轮、
ask_user ≤max_ask_user 次/轮）→ 结构化诊断 JSON + 通俗摘要 → 落库。

运行参数（max_tool_rounds / max_ask_user / max_tokens / temperature /
tool_result_max_chars / force_first_round_search）实时读 config.json agent 节
（superadmin 后台在线可调，缺省见 config.AGENT_DEFAULTS），改完对后续轮次即生效。
force_first_round_search 开启时，会话首轮首次请求经 API 层 tool_choice 锁定
kb_search（硬强制，区别于系统提示词的软约束；要求供应商支持 tool_choice）。

流式事件通过 emit 回调推送（SSE）：delta/reasoning/tool_start/tool_result/
pending_question/diag_final/done/error。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable

from sqlalchemy.orm import Session

from backend.config import agent_param
from backend.core.providers.llm import (
    ChatResult,
    LLMProvider,
    ToolCall,
    get_main_provider,
    provider_label,
)
from backend.core.tools.registry import ToolContext, ToolSpec, build_tool_specs, tool_specs_to_openai
from backend.db.models import Message, Session as ChatSession, UsageStat

# 模型偶尔无视提示词在选项里自带兜底项，与前端固定附加的「不知道/不清楚」语义重复，统一剥离
_UNCLEAR_OPT_PAT = re.compile(r"不知道|不清楚|记不清|不确定|没试过|还没试|不了解")


def _strip_unclear_options(questions: list[dict]) -> list[dict]:
    for q in questions:
        opts = q.get("options")
        if isinstance(opts, list):
            q["options"] = [o for o in opts if isinstance(o, str) and not _UNCLEAR_OPT_PAT.search(o)]
    return questions

SYSTEM_PROMPT_TEMPLATE = """# 角色
你是新能源汽车维修诊断助手，服务对象是车主与门店技师。今天的日期是 {today}。

# 工具触发策略（必须遵守）
- 涉及任何故障判断：必须先调用 kb_search / dtc_lookup 查证据，禁止凭训练记忆编造故障结论。
- 用简短关键词检索；首次未命中就改写关键词换角度再查（例如"冬季衰减"→"低温 续航 下降"）。
- 有故障码时优先 dtc_lookup 精确查码；码表和知识库都没有的内容再用 web_search 联网核实。
- web_search 仅作补充证据：仅凭联网单源支撑的判断不得写入 hypotheses，只能列入 pending_checks；与知识库/码表证据冲突时以知识库为准。
- 检索未命中或证据不足时如实说明，不臆断。
- 开始诊断先调 get_vehicle_profile 看车主车辆档案与历史记录；缺少"只有车主才知道"的场景信息（起病时机、充电习惯、使用环境）时，用 ask_user 提问：一次只问一组最关键的，优先查资料而不是问人。
- ask_user 的 options 只放具体、互斥的场景描述（如颜色、状态、症状），禁止放「不知道/不清楚/记不清/不确定/还没试过」之类兜底项——前端会自动附加兜底选项，重复出现会造成困惑。
- 车主可能对某个问题回答"不知道/不清楚"（前端自动提供该选项）：此时把该项列入 pending_checks，基于已有证据直接给结论，禁止就同一信息再次追问。
- 每获得关键事实（车型确认、车主回答、检查结论），调用 update_case_notes 更新诊断状态卡（跨轮记忆，压缩后也不丢）。
- 证据充分后立即输出结论，不要为了查而查。

# 输出格式（两段；面向车主，禁止暴露检索细节）
1. 先用 2~4 句话给出通俗解释（面向车主，避免堆术语）。
2. 然后输出一个 ```json 代码块，字段：
   {{"severity": "green|yellow|red",
     "summary": "一句话结论",
     "hypotheses": [{{"title": "故障假设"}}],
     "steps": ["建议的检修步骤"],
     "pending_checks": ["仍需到店确认的事项"]}}
严重度标准：green=正常现象或无需处理；yellow=功能性异常，需尽快检查；red=安全风险，立即停止使用并进店。

# 车主可见性（必须遵守）
- 正文与 JSON 中禁止出现 [1]、[网2] 式引用标注，禁止出现「依据 kb_search/dtc_lookup/来源：」式查证详情——查证过程由系统界面展示，知识库原文细节不暴露给车主。
- hypotheses 只给简短的故障假设标题（车主能看懂的话），依据内部自行核对，不写进输出。"""

ASK_USER_TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": "向车主/店员提问收集只有对方知道的信息（场景、时机、习惯）。一次只问一组最关键的；可离线续答：对方不在线时问题会挂起，回复后自动继续诊断。注意：前端会为每个问题自动附加「不知道/不清楚」选项，对方可能以此作答。",
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "description": "问题列表，1~3 个",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "问题标识，如 temp"},
                            "question": {"type": "string", "description": "问题文本"},
                            "options": {
                                "type": "array",
                                "description": "候选项（点选作答），2~4 个；只放具体、互斥的场景描述，禁止包含「不知道/不清楚/记不清/不确定/还没试过」类兜底项（前端自动附加兜底，出现即重复）",
                                "items": {"type": "string"},
                            },
                            "allow_free": {"type": "boolean", "description": "是否允许自由输入，默认 true"},
                        },
                        "required": ["id", "question", "options"],
                    },
                }
            },
            "required": ["questions"],
        },
    },
}

UPDATE_CASE_NOTES_SPEC = {
    "type": "function",
    "function": {
        "name": "update_case_notes",
        "description": "更新诊断状态卡（本会话跨轮记忆，上下文压缩后也不丢失）。每当获得关键事实就调用：车型确认、车主回答、检查结论、待确认事项变化。",
        "parameters": {
            "type": "object",
            "properties": {
                "vehicle": {"type": "string", "description": "车型/年款/动力类型/VIN（确认后更新，如「2023款 比亚迪汉 EV」）"},
                "symptoms": {
                    "type": "array", "items": {"type": "string"},
                    "description": "已确认的症状/现象清单（追加式，只传新增项）",
                },
                "checked": {
                    "type": "array", "items": {"type": "string"},
                    "description": "已排查项与结论（追加式，如「kb_search：低温限功率属正常」）",
                },
                "pending": {
                    "type": "array", "items": {"type": "string"},
                    "description": "仍待确认的事项（追加式；已确认的不要再留）",
                },
            },
        },
    },
}


def normalize_diag(diag: dict) -> dict:
    """归一化模型诊断 JSON 到展示契约：hypotheses=[{title}]、steps/pending_checks=[str]。

    模型不一定守 JSON 契约（实测会把 hypotheses 给成字符串数组、或用 cause/name 作键），
    在入库与下发前统一归一，消费方（预约摘要卡/案例沉淀/前端诊断卡）不再各自防御。
    evidence 字段已废弃：系统提示词要求依据内部核对不写入输出（车主可见性），
    前端车主端也不渲染来源详情——契约收敛为纯 title，模型若仍带回 evidence 一并剥除。
    """
    def _str_list(v: object) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(item).strip() for item in v if isinstance(item, (str, int, float)) and str(item).strip()]

    hypotheses: list[dict] = []
    raw = diag.get("hypotheses")
    if isinstance(raw, list):
        for h in raw:
            if isinstance(h, str) and h.strip():
                hypotheses.append({"title": h.strip()})
            elif isinstance(h, dict):
                title = h.get("title") or h.get("cause") or h.get("name") or ""
                if isinstance(title, str) and title.strip():
                    hypotheses.append({"title": title.strip()})

    normalized = dict(diag)
    normalized["hypotheses"] = hypotheses
    normalized["steps"] = _str_list(diag.get("steps"))
    normalized["pending_checks"] = _str_list(diag.get("pending_checks"))
    if not isinstance(diag.get("summary"), str):
        normalized["summary"] = str(diag.get("summary") or "")
    if not isinstance(diag.get("severity"), str) or not diag.get("severity"):
        normalized["severity"] = "yellow"
    return normalized


def _parse_diag_json(content: str) -> dict | None:
    """从最终回复剥离 ```json fence 解析结构化诊断（flash 习惯带 fence 输出）。"""
    m = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    if not m:
        m = re.search(r"(\{[^\{\}`]*\"severity\".*\})", content, re.DOTALL)
        if not m:
            return None
    try:
        data = json.loads(m.group(1))
        if isinstance(data, dict) and "severity" in data:
            return normalize_diag(data)
    except json.JSONDecodeError:
        pass
    return None


def _split_summary_and_json(content: str) -> tuple[str, dict | None]:
    diag = _parse_diag_json(content)
    summary = re.sub(r"```json\s*\{.*?\}\s*```", "", content, flags=re.DOTALL).strip()
    return summary, diag


class AgentRunner:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider or get_main_provider()
        self.specs: list[ToolSpec] = build_tool_specs()
        self.tool_openai = (
            tool_specs_to_openai(self.specs) + [ASK_USER_TOOL_SPEC, UPDATE_CASE_NOTES_SPEC]
        )

    def build_system_prompt(self) -> str:
        # 状态卡不放 system（每轮变化会破坏 DeepSeek 前缀缓存），改为末尾临时注入
        return SYSTEM_PROMPT_TEMPLATE.format(today=datetime.now().strftime("%Y-%m-%d"))

    def _merge_case_notes(self, session: ChatSession, args: dict) -> None:
        """update_case_notes 合并策略：字符串覆盖，列表追加去重（保序）。"""
        notes = dict(session.case_notes or {})
        for key in ("vehicle",):
            v = args.get(key)
            if isinstance(v, str) and v.strip():
                notes[key] = v.strip()
        for key in ("symptoms", "checked", "pending"):
            v = args.get(key)
            if isinstance(v, str) and v.strip():
                v = [v.strip()]  # 模型传字符串 → 视为单项，统一走追加
            if isinstance(v, list):
                prev = notes.get(key, [])
                if isinstance(prev, str) and prev.strip():
                    # 旧值是字符串（模型首轮未守列表格式）→ 迁移为单元素，禁止逐字拆分
                    merged = [prev.strip()]
                else:
                    merged = [x for x in prev if isinstance(x, str)]
                for item in v:
                    if isinstance(item, str) and item.strip() and item.strip() not in merged:
                        merged.append(item.strip())
                notes[key] = merged
        session.case_notes = notes

    def _build_tail_block(self, db: Session, session: ChatSession) -> str:
        """每轮临时注入块（mark_as_temp 式）：状态卡 + 车辆档案一行摘要 + 历史诊断。
        拼在上下文最尾端、不写入对话历史；无任何信息时不注入。"""
        from backend.core.tools.registry import vehicle_summary_line

        notes = session.case_notes or {}
        vehicle_line = vehicle_summary_line(db, session)
        if not notes and not vehicle_line:
            return ""
        lines = ["[诊断状态卡（临时注入，不入对话历史；用 update_case_notes 工具维护）]"]
        if notes:
            lines.append(json.dumps(notes, ensure_ascii=False, indent=1))
        if vehicle_line:
            lines.append(f"[车辆档案]\n{vehicle_line}")
        return "\n".join(lines)

    async def _record_usage(self, db: Session, session: ChatSession, usage: dict, slot: str) -> None:
        if not usage:
            return
        db.add(
            UsageStat(
                tenant_id=session.tenant_id,
                user_id=session.user_id,
                slot=slot,
                provider=provider_label(self.provider.base_url),
                model=self.provider.model,
                tokens_in=int(usage.get("prompt_tokens", 0)),
                tokens_out=int(usage.get("completion_tokens", 0)),
                latency_ms=0,
            )
        )
        db.commit()

    async def run_turn(
        self,
        db: Session,
        session: ChatSession,
        history: list[dict],
        user_content: str | None,
        emit: Callable[[str, dict], Awaitable[None]],
    ) -> str:
        """跑一轮 Agentic 循环（user_content=None 表示续答场景，从历史中的工具结果继续）。

        返回终态：'done' | 'waiting_user' | 'error'。
        """
        # 按本轮会话重建工具（get_vehicle_profile 依赖 ctx 定位车主/车辆）
        self.specs = build_tool_specs(ToolContext(session=session))
        self.tool_openai = (
            tool_specs_to_openai(self.specs) + [ASK_USER_TOOL_SPEC, UPDATE_CASE_NOTES_SPEC]
        )
        messages: list[dict] = [{"role": "system", "content": self.build_system_prompt()}]
        # 双阀门压缩：超轮数/token 先截断并摘要，再进上下文
        from backend.core.agent.compressor import maybe_compress

        history = await maybe_compress(db, session, history)
        messages.extend(history)
        tail_block = self._build_tail_block(db, session)
        if tail_block:
            messages.append({"role": "system", "content": tail_block})
        if user_content:
            messages.append({"role": "user", "content": user_content})
            db.add(
                Message(
                    tenant_id=session.tenant_id, session_id=session.id, role="user", content=user_content
                )
            )

        tool_round = 0
        ask_user_count = 0
        assistant_text = ""
        pending_questions: list[dict] | None = None

        # 运行参数每轮实时取（superadmin 后台改配置即时生效）
        max_tool_rounds = int(agent_param("max_tool_rounds"))
        max_ask_user = int(agent_param("max_ask_user"))
        max_tokens = int(agent_param("max_tokens"))
        temperature = float(agent_param("temperature"))
        tool_result_max_chars = int(agent_param("tool_result_max_chars"))
        # 首轮硬强制检索：仅对「响应会话第一条用户消息的本次循环首轮请求」生效
        force_first_search = bool(agent_param("force_first_round_search")) and user_content is not None
        is_first_turn = not any(m.get("role") == "assistant" for m in history)

        while True:
            content = ""
            finish = ""
            usage: dict = {}
            tool_calls: list[ToolCall] = []

            request_params: dict[str, Any] = {"max_tokens": max_tokens, "temperature": temperature}
            if force_first_search and is_first_turn and tool_round == 0:
                request_params["tool_choice"] = {"type": "function", "function": {"name": "kb_search"}}
            async for event in self.provider.chat_stream(messages, tools=self.tool_openai, **request_params):
                if event["type"] == "delta":
                    content += event["content"]
                    await emit("delta", {"content": event["content"]})
                elif event["type"] == "finish":
                    finish = event["reason"]
                    tool_calls = event["tool_calls"]
                    usage = event["usage"]
                elif event["type"] == "error":
                    await emit("error", {"message": event["message"]})
                    db.commit()
                    return "error"

            await self._record_usage(db, session, usage, "main")
            assistant_text += content

            if not tool_calls:
                # 最终回复：落库 + 解析结构化诊断
                summary, diag = _split_summary_and_json(assistant_text)
                db.add(
                    Message(
                        tenant_id=session.tenant_id,
                        session_id=session.id,
                        role="assistant",
                        content=summary,
                        diag_json=diag,
                        tokens_in=int(usage.get("prompt_tokens", 0)),
                        tokens_out=int(usage.get("completion_tokens", 0)),
                    )
                )
                if diag:
                    await emit("diag_final", diag)
                await emit("done", {})
                db.commit()
                return "done"

            # 工具调用轮：先落 assistant 消息（含 tool_calls），再逐个执行回填
            tool_round += 1
            if tool_round > max_tool_rounds:
                truncated = "（已达单轮工具调用上限，基于已有证据直接给结论）"
                summary, diag = _split_summary_and_json(assistant_text) if assistant_text.strip() else (truncated, None)
                db.add(
                    Message(
                        tenant_id=session.tenant_id,
                        session_id=session.id,
                        role="assistant",
                        content=summary or truncated,
                        diag_json=diag,
                    )
                )
                await emit("diag_final", diag or {"severity": "yellow", "summary": truncated, "hypotheses": [], "steps": [], "pending_checks": []})
                await emit("done", {})
                db.commit()
                return "done"

            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
                        for tc in tool_calls
                    ],
                }
            )
            db.add(
                Message(
                    tenant_id=session.tenant_id,
                    session_id=session.id,
                    role="assistant",
                    content=content,
                    tool_calls=[{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in tool_calls],
                )
            )
            db.commit()

            for ti, tc in enumerate(tool_calls):
                if tc.name == "update_case_notes":
                    try:
                        args = json.loads(tc.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    self._merge_case_notes(session, args if isinstance(args, dict) else {})
                    result = "状态卡已更新：" + json.dumps(session.case_notes, ensure_ascii=False)
                    result = result[:400]
                    await emit("tool_result", {"name": tc.name, "result": "状态卡已更新"})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                    db.add(
                        Message(
                            tenant_id=session.tenant_id, session_id=session.id,
                            role="tool", content=result, tool_call_id=tc.id,
                        )
                    )
                    db.commit()
                    continue

                if tc.name == "ask_user":
                    ask_user_count += 1
                    if ask_user_count > max_ask_user:
                        result = "（本轮提问次数已达上限）请基于现有证据直接给结论，缺的信息列为 pending_checks。"
                        await emit("tool_result", {"name": tc.name, "result": result})
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                        # 存根必须落库：否则库里留下无响应的 tool_call，重放历史时 API 会 400
                        db.add(
                            Message(
                                tenant_id=session.tenant_id, session_id=session.id,
                                role="tool", content=result, tool_call_id=tc.id,
                            )
                        )
                        db.commit()
                        continue
                    try:
                        questions = json.loads(tc.arguments or "{}").get("questions", [])
                    except json.JSONDecodeError:
                        questions = []
                    questions = _strip_unclear_options(questions)
                    pending_questions = questions
                    session.pending_questions = questions
                    # 同批排在 ask_user 之后、未执行的工具调用：落存根响应行，
                    # 保证每个 tool_call 都有配对 tool 消息（重放历史不 400）
                    stub = "（同批的提问已发出，此调用本轮未执行）"
                    for rest in tool_calls[ti + 1:]:
                        db.add(
                            Message(
                                tenant_id=session.tenant_id, session_id=session.id,
                                role="tool", content=stub, tool_call_id=rest.id,
                            )
                        )
                    # 注意：assistant(tool_calls) 消息已在本轮通用路径落库（含 ask_user 调用），
                    # 此处不再重复插入，否则续答时历史出现连续两条 assistant tool_calls，模型返回 400
                    await emit("pending_question", {"tool_call_id": tc.id, "questions": questions})
                    db.commit()
                    return "waiting_user"

                spec = next((s for s in self.specs if s.name == tc.name), None)
                await emit("tool_start", {"name": tc.name, "arguments": tc.arguments})
                if spec is None:
                    result = f"未知工具 {tc.name}。"
                else:
                    try:
                        args = json.loads(tc.arguments or "{}")
                        result = await spec.handler(db, **args)
                    except json.JSONDecodeError:
                        result = "工具参数不是合法 JSON，请修正后重试。"
                    except TypeError as exc:
                        result = f"工具参数错误：{exc}"
                    except Exception as exc:  # noqa: BLE001  工具故障转为工具结果，循环不崩
                        result = f"工具执行失败：{exc}。请换用其他工具或基于已有证据作答。"
                result = result[:tool_result_max_chars]  # 单轮工具结果预算（≤4k token 上限的近似）
                await emit("tool_result", {"name": tc.name, "result": result[:300]})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                db.add(
                    Message(
                        tenant_id=session.tenant_id,
                        session_id=session.id,
                        role="tool",
                        content=result,
                        tool_call_id=tc.id,
                    )
                )
                db.commit()

        # unreachable
