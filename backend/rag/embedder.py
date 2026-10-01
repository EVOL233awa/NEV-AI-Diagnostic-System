"""bge-m3 嵌入客户端（OpenAI 兼容 /v1/embeddings）。

2026-09-25 实测：本地 llama-server :11436 返回 1024 维，data[i].embedding，usage 正常。
2026-09-29 实测：硅基流动 BAAI/bge-m3（https://api.siliconflow.cn/v1）同为 1024 维，
单条 P50 约 150-190ms，batch=64 均摊约 25ms/条。
embedding_key 非空即视为远端 API，请求携带 Bearer 认证；两者接口形态一致。
嵌入服务不可达/认证失败均抛 EmbedderUnavailable，检索引擎据此退化为纯关键词路。
"""
from __future__ import annotations

import json
import threading
import urllib.request
from collections import OrderedDict
from typing import Any

from backend.config import settings

# 禁用系统代理：本机代理环境变量（SOCKS）会干扰云端 API 与本地回环的直连
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 查询嵌入 LRU 缓存：同文本免二次云端调用（追问轮次/重试/同题复查场景）。
# 512 条 × 1024 维 ≈ 4MB，2C2G 可承载；文档导入批量的重复文本同样受益。
_EMBED_CACHE_MAX = 512
_embed_cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
_embed_lock = threading.Lock()


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
        self.dim = 1024  # bge-m3 实测维度（硅基流动云端同为 1024）

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[tuple[float, ...] | None] = [None] * len(texts)
        missing: list[int] = []
        with _embed_lock:
            for i, text in enumerate(texts):
                cached = _embed_cache.get(text)
                if cached is not None:
                    _embed_cache.move_to_end(text)
                    results[i] = cached
                else:
                    missing.append(i)
        if missing:
            missing_texts = list(dict.fromkeys(texts[i] for i in missing))
            fetched = self._request_embeddings(missing_texts)
            by_text = dict(zip(missing_texts, fetched))
            with _embed_lock:
                for i in missing:
                    vector = tuple(by_text[texts[i]])
                    results[i] = vector
                    _embed_cache[texts[i]] = vector
                    _embed_cache.move_to_end(texts[i])
                while len(_embed_cache) > _EMBED_CACHE_MAX:
                    _embed_cache.popitem(last=False)
        return [list(v) if v is not None else [] for v in results]

    def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
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
