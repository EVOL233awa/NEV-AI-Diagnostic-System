"""压缩器离线测试：双阀门、边界复用（防回流回归）、降级、usage 落账。

模型调用全部 mock（FakeProvider），不打 DeepSeek；DB 用临时测试库。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.core.agent import compressor
from backend.db.models import Session as ChatSession
from backend.db.models import UsageStat


@dataclass
class _FakeResult:
    content: str = "摘要：车主反映低温续航衰减，已建议检查电池健康度并预约到店检测。"
    usage: dict[str, int] = field(
        default_factory=lambda: {"prompt_tokens": 120, "completion_tokens": 60}
    )


class _FakeProvider:
    model = "fake-compressor"
    api_key = "test-key"
    base_url = "https://api.deepseek.com"
    fail = False

    async def chat(self, messages: list[dict], **kwargs: Any) -> _FakeResult:
        if self.fail:
            raise RuntimeError("压缩模型不可用")
        return _FakeResult()


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> _FakeProvider:
    provider = _FakeProvider()
    monkeypatch.setattr(compressor, "get_background_provider", lambda: provider)
    return provider


def _rounds(n: int, big: bool = False) -> list[dict]:
    """n 轮假对话（每轮 user+assistant 各一条，_id 连续自 1 起）。"""
    msgs: list[dict] = []
    mid = 1
    for i in range(n):
        content = f"问题{i}：电动车充电场景描述" + ("细节" * 40 if big else "")
        msgs.append({"_id": mid, "role": "user", "content": content})
        mid += 1
        msgs.append({"_id": mid, "role": "assistant", "content": f"回答{i}：排查建议"})
        mid += 1
    return msgs


def _new_session(db) -> ChatSession:
    session = ChatSession(tenant_id=1, user_id=1, title="压缩测试", channel="owner")
    db.add(session)
    db.commit()
    return session


def test_estimate_tokens_basic() -> None:
    assert compressor.estimate_tokens([]) == 0
    # 160 字符 / 1.6 = 100，加每条固定开销 4
    assert compressor.estimate_tokens([{"content": "x" * 160}]) == 104
    assert compressor.estimate_tokens([{"content": None}, {"content": "ab"}]) == 1 + 8


def test_split_rounds_groups_by_user() -> None:
    history = [
        {"role": "assistant", "content": "开场"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1", "tool_calls": [{"id": "t1"}]},
        {"role": "tool", "tool_call_id": "t1", "content": "结果"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    rounds = compressor._split_rounds(history)
    assert len(rounds) == 3
    assert [m["role"] for m in rounds[0]] == ["assistant"]
    assert [m["role"] for m in rounds[1]] == ["user", "assistant", "tool"]
    assert [m["role"] for m in rounds[2]] == ["user", "assistant"]


def test_old_text_truncates_and_lists_tools() -> None:
    old = [
        {"role": "user", "content": "问" * 500},
        {"role": "assistant", "content": "答" * 400, "tool_calls": [
            {"function": {"name": "kb_search"}}, {"function": {"name": "dtc_lookup"}},
        ]},
        {"role": "tool", "content": "果" * 400},
    ]
    text = compressor._old_text(old, "旧摘要内容")
    assert "旧摘要内容" in text
    assert "调用工具：kb_search,dtc_lookup" in text
    assert len([ln for ln in text.splitlines() if ln.startswith("[工具结果]")]) == 1
    tool_line = next(ln for ln in text.splitlines() if ln.startswith("[工具结果]"))
    assert len(tool_line) < 320  # 300 字截断 + 前缀
    user_line = next(ln for ln in text.splitlines() if ln.startswith("[车主]"))
    assert len(user_line) < 420  # 400 字截断 + 前缀


def test_no_overflow_passthrough(db_session, fake_provider) -> None:
    session = _new_session(db_session)
    history = _rounds(5)
    out = asyncio.run(compressor.maybe_compress(db_session, session, history))
    assert len(out) == 10
    assert all("_id" not in m for m in out)
    assert session.context_summary is None
    assert session.summarized_until_id is None


def test_round_overflow_creates_summary(db_session, fake_provider) -> None:
    session = _new_session(db_session)
    history = _rounds(30)  # 60 条、30 轮 > MAX_ROUNDS=20 → 前 10 轮溢出
    out = asyncio.run(compressor.maybe_compress(db_session, session, history))
    assert out[0]["role"] == "system"
    assert "前情摘要" in out[0]["content"]
    assert fake_provider.fail is False
    # 溢出最后一条 _id = 20（每轮 2 条，10 轮）
    assert session.summarized_until_id == 20
    assert session.context_summary
    # 保留段 = 40 条原文 + 1 条摘要注入
    assert len(out) == 41
    usage = db_session.query(UsageStat).filter_by(slot="compression", model="fake-compressor").all()
    assert len(usage) == 1
    assert usage[0].tokens_in == 120 and usage[0].tokens_out == 60


def test_degrade_to_truncation_on_failure(db_session, fake_provider) -> None:
    fake_provider.fail = True
    session = _new_session(db_session)
    history = _rounds(30)
    before = db_session.query(UsageStat).filter_by(slot="compression").count()
    out = asyncio.run(compressor.maybe_compress(db_session, session, history))
    assert all(m["role"] != "system" for m in out)
    assert len(out) == 40  # 纯截断：只保留边界之后的 40 条
    assert session.summarized_until_id == 20
    assert session.context_summary is None
    # 降级路径不产生新的压缩调用流水
    assert db_session.query(UsageStat).filter_by(slot="compression").count() == before


def test_boundary_reuse_no_reflow(db_session, fake_provider) -> None:
    """回归：已有压缩边界且本轮未新增压缩时，已压缩原文不得回流上下文。"""
    session = _new_session(db_session)
    history = _rounds(30)
    asyncio.run(compressor.maybe_compress(db_session, session, history))
    assert session.summarized_until_id == 20

    # 模拟下一轮 build_history 重新拉全量：同样 60 条（_id 1..60）
    history_again = _rounds(30)
    out = asyncio.run(compressor.maybe_compress(db_session, session, history_again))
    assert out[0]["role"] == "system"
    assert "前情摘要" in out[0]["content"]
    # 只应包含 _id 21..60 的 40 条，不得出现已压缩原文
    assert len(out) == 41
    returned_texts = {m["content"] for m in out[1:]}
    compressed_texts = {m["content"] for m in history_again if m["_id"] <= 20}
    assert not (returned_texts & compressed_texts)
