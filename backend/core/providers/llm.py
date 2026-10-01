"""LLM Provider 层：OpenAI 兼容聊天实现的抽象与 DeepSeek 适配。

双 Key 隔离：主对话用 main_key，后台任务（压缩/标题/抽取）用 background_key。
流式按 OpenAI SSE 协议解析；usage 统一通过 UsageRecord 回传供 usage_stats 落账。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from backend.config import settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # 原始 JSON 字符串，由调用方解析


@dataclass
class ChatResult:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


class LLMProvider:
    """OpenAI 兼容 chat/completions 的异步客户端。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout_s: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}

    def _payload(self, messages: list[dict], tools: list[dict] | None, stream: bool, **params: Any) -> dict:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }
        if tools:
            body["tools"] = tools
        body.update(params)
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    def _client(self) -> httpx.AsyncClient:
        # trust_env=False：忽略本机代理环境变量（SOCKS 代理会破坏 API 直连）
        return httpx.AsyncClient(timeout=self.timeout_s, trust_env=False)

    async def chat(self, messages: list[dict], tools: list[dict] | None = None, **params: Any) -> ChatResult:
        body = self._payload(messages, tools, stream=False, **params)
        async with self._client() as client:
            resp = await client.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        choice = data["choices"][0]
        message = choice.get("message", {})
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=tc["function"]["arguments"])
            for tc in message.get("tool_calls") or []
        ]
        return ChatResult(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
            reasoning=message.get("reasoning_content") or "",
        )

    async def chat_stream(
        self, messages: list[dict], tools: list[dict] | None = None, **params: Any
    ) -> AsyncIterator[dict]:
        """流式输出，yield 事件字典：
        {type: delta, content} / {type: reasoning, content} /
        {type: finish, reason, tool_calls, usage} / {type: error, message}
        """
        body = self._payload(messages, tools, stream=True, **params)
        tool_acc: dict[int, dict] = {}
        finish_reason = ""
        usage: dict[str, Any] = {}
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", json=body, headers=self._headers()
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        chunk = json.loads(data_str)
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        for choice in chunk.get("choices", []):
                            delta = choice.get("delta") or {}
                            if delta.get("content"):
                                yield {"type": "delta", "content": delta["content"]}
                            if delta.get("reasoning_content"):
                                yield {"type": "reasoning", "content": delta["reasoning_content"]}
                            for tc in delta.get("tool_calls") or []:
                                idx = tc.get("index", 0)
                                acc = tool_acc.setdefault(
                                    idx, {"id": "", "name": "", "arguments": ""}
                                )
                                if tc.get("id"):
                                    acc["id"] = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    acc["name"] = fn["name"]
                                if fn.get("arguments"):
                                    acc["arguments"] += fn["arguments"]
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]
        except httpx.HTTPStatusError as exc:
            yield {"type": "error", "message": f"模型服务返回 {exc.response.status_code}"}
            return
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            yield {"type": "error", "message": f"模型服务连接异常：{exc}"}
            return

        yield {
            "type": "finish",
            "reason": finish_reason,
            "tool_calls": [
                ToolCall(id=v["id"] or f"call_{i}", name=v["name"], arguments=v["arguments"])
                for i, v in sorted(tool_acc.items())
            ],
            "usage": usage,
        }


def provider_label(base_url: str) -> str:
    """从 base_url 派生供应商标识（usage_stats.provider 列）：主机名去掉 api. 前缀。

    槽位可经 superadmin 换成任意 OpenAI 兼容供应商，统计维度须跟随实际供应商而非写死；
    主机名缺 scheme 时按 https 补全解析，仍无主机名则原样截断（列宽 32）。
    """
    parsed = urlparse(base_url if "//" in base_url else f"https://{base_url}")
    return str(parsed.hostname or base_url).removeprefix("api.")[:32]


def get_main_provider() -> LLMProvider:
    ds = settings.deepseek
    return LLMProvider(
        base_url=str(ds.get("base_url") or "https://api.deepseek.com").rstrip("/"),
        api_key=ds.get("main_key", ""),
        model=ds.get("main_model", "deepseek-flash"),
    )


def get_background_provider() -> LLMProvider:
    """后台任务槽位（压缩/标题/抽取）：独立 Key，防挤占前台限速配额。

    background_base_url 缺省跟随主对话 base_url（老配置零迁移）。
    """
    ds = settings.deepseek
    return LLMProvider(
        base_url=str(ds.get("background_base_url") or ds.get("base_url") or "https://api.deepseek.com").rstrip("/"),
        api_key=ds.get("background_key", ds.get("main_key", "")),
        model=ds.get("background_model", "deepseek-flash"),
    )
