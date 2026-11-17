"""标题/状态卡抽取的离线单测——aux provider 全 mock，绝不触真实 API。

覆盖：JSON 剥取（纯/fence/噪声前后缀）、非法输出降级 None、字段清洗
（vehicle 截断、symptoms 过滤+上限）、aux provider 参数（thinking disabled）、
异常降级、标题 strip 与 16 字硬截。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

import backend.core.agent.extractor as extractor
from backend.core.providers.llm import ChatResult


class _StubProvider:
    def __init__(self, content: str = "", error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.captured: dict | None = None
        self.messages: list[dict] | None = None

    async def chat(self, messages: list[dict], **params) -> ChatResult:
        self.captured = params
        self.messages = messages
        if self.error is not None:
            raise self.error
        return ChatResult(content=self.content)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> _StubProvider:
    stub = _StubProvider()
    monkeypatch.setattr(extractor, "get_aux_provider", lambda: stub)
    return stub


def _run(text: str) -> dict | None:
    return asyncio.run(extractor.extract_case_notes(text))


def _title(text: str) -> str | None:
    return asyncio.run(extractor.generate_session_title(text))


class TestExtractCaseNotes:
    def test_plain_json(self, provider: _StubProvider):
        provider.content = json.dumps(
            {"vehicle": "比亚迪 汉 EV 2023", "symptoms": ["高速发飘", "方向盘抖"]}, ensure_ascii=False
        )
        notes = _run("换了胎之后高速发飘")
        assert notes == {"vehicle": "比亚迪 汉 EV 2023", "symptoms": ["高速发飘", "方向盘抖"]}
        # 三模型收敛：走辅助槽位，且固定关闭思考
        assert provider.captured is not None
        assert provider.captured["thinking"] == {"type": "disabled"}

    def test_json_fence_and_noise(self, provider: _StubProvider):
        body = json.dumps({"vehicle": "特斯拉 M3", "symptoms": ["充电慢"]}, ensure_ascii=False)
        provider.content = f"好的，以下是抽取结果：\n```json\n{body}\n```\n请查收。"
        notes = _run("充电慢")
        assert notes == {"vehicle": "特斯拉 M3", "symptoms": ["充电慢"]}

    @pytest.mark.parametrize("bad", ["", "   ", "我不会回答这个问题", "[1,2,3]", "{broken"])
    def test_invalid_output_returns_none(self, provider: _StubProvider, bad: str):
        provider.content = bad
        assert _run("随便描述") is None

    def test_field_sanitizing(self, provider: _StubProvider):
        provider.content = json.dumps(
            {
                "vehicle": "v" * 100,
                "symptoms": ["a", "  ", 123, "b", "c", "d", "e", "f"],
                "extra": "ignored",
            },
            ensure_ascii=False,
        )
        notes = _run("x")
        assert notes["vehicle"] == "v" * 64
        assert notes["symptoms"] == ["a", "b", "c", "d", "e"]  # 空串/非字符串过滤 + 上限 5

    def test_provider_error_returns_none(self, provider: _StubProvider):
        provider.error = httpx.ConnectError("refused")
        assert _run("x") is None

    def test_empty_dict_returns_none(self, provider: _StubProvider):
        provider.content = "{}"
        assert _run("x") is None


class TestGenerateSessionTitle:
    def test_plain(self, provider: _StubProvider):
        provider.content = "冬天续航掉电快"
        assert _title("冬天续航掉得厉害") == "冬天续航掉电快"

    def test_strip_quotes_and_punct(self, provider: _StubProvider):
        provider.content = '《充电跳枪是怎么回事》。！'
        assert _title("x") == "充电跳枪是怎么回事"

    def test_hard_truncate_16(self, provider: _StubProvider):
        provider.content = "这个标题实在是太长了远远超过十六个字的限制需要硬截断处理"
        assert _title("x") == "这个标题实在是太长了远远超过十六个字"[:16]
        assert len(_title("x")) == 16

    def test_empty_returns_none(self, provider: _StubProvider):
        provider.content = "   "
        assert _title("x") is None

    def test_provider_error_returns_none(self, provider: _StubProvider):
        provider.error = httpx.ReadTimeout("timeout")
        assert _title("x") is None
