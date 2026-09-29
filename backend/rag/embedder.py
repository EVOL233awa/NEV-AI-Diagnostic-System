"""bge-m3 嵌入客户端（OpenAI 兼容 /v1/embeddings）。

2026-09-25 实测：本地 llama-server :11436 返回 1024 维，data[i].embedding，usage 正常。
2026-09-29 实测：硅基流动 BAAI/bge-m3（https://api.siliconflow.cn/v1）同为 1024 维，
单条 P50 约 150-190ms，batch=64 均摊约 25ms/条。
embedding_key 非空即视为远端 API，请求携带 Bearer 认证；两者接口形态一致。
嵌入服务不可达/认证失败均抛 EmbedderUnavailable，检索引擎据此退化为纯关键词路（§4 容错）。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from backend.config import settings

# 禁用系统代理：本机代理环境变量（SOCKS）会干扰云端 API 与本地回环的直连
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class EmbedderUnavailable(RuntimeError):
    pass


class Embedder:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: int = 20,
    ) -> None:
        lm = settings.local_models
        # base_url 约定不含 /v1（代码层统一拼接）；容错去掉误配的 /v1 尾缀
        self.base_url = (base_url or str(lm.get("embedding_url", "http://127.0.0.1:11436"))).rstrip("/").removesuffix("/v1")
        self.model = model or str(lm.get("embedding_model", "bge-m3"))
        self.api_key = str(lm["embedding_key"]) if lm.get("embedding_key") else ""
        self.timeout_s = timeout_s
        self.dim = 1024  # bge-m3 实测维度（阶段 1 首日核验；硅基流动云端同为 1024）

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = json.dumps({"input": texts, "model": self.model}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/embeddings",
            data=payload,
            headers=headers,
        )
        try:
            with _OPENER.open(req, timeout=self.timeout_s) as resp:
                data: dict[str, Any] = json.load(resp)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EmbedderUnavailable(f"嵌入服务不可达（{self.base_url}）：{exc}") from exc
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        vectors = [item["embedding"] for item in items]
        if len(vectors) != len(texts):
            raise EmbedderUnavailable(f"嵌入返回数量不符：期望 {len(texts)}，实际 {len(vectors)}")
        return vectors
