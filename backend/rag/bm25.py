"""关键词检索路：jieba 分词 + rank-bm25（专治故障码/术语字面命中）。

索引在内存单例中维护：进程启动或检索 miss 时从 kb_chunks 全量加载，
新增/删除知识块时增量更新。数据量为单店万级块内，Python 层 BM25 毫秒级。
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import KbChunk, KbDocument

# 领域词进 jieba 词典，避免被切碎。词条来自实测切碎点：
# 动力电池组→动力电池+组、快充口→快充+口、充电枪→充电+枪锁（错切）、高压配电箱→高压+配电箱
for _w in (
    "电池管理系统", "电机控制器", "整车控制器", "动力电池", "动力电池组", "动力电池包",
    "电池包", "电池模组", "单体电池", "充电桩", "快充", "慢充", "快充口", "慢充口",
    "充电枪", "充电口", "车载充电机", "高压配电箱", "冷却液", "冷却系统", "热管理",
    "热失控", "续航里程", "绝缘故障", "绝缘电阻", "高压互锁", "预充", "继电器", "编码器",
    "续航衰减", "低温衰减", "回收失效", "充电中断", "充电跳枪", "跳枪", "蓄电池",
    "仪表灯", "故障灯", "DC-DC", "SOC", "SOH", "BMS", "MCU", "VCU", "OBC", "DCDC",
    "IGBT", "CAN", "DTC", "P0A1F",
):
    jieba.add_word(_w, freq=1000)
    if _w != _w.lower():
        jieba.add_word(_w.lower(), freq=1000)  # 分词发生在 lower() 之后，形态须一致

# 语料中出现的全部 DTC 码动态入词典：jieba 默认已把字母数字串整词保留，
# 显式注入是防御性锚定（码与中文粘连时的边界歧义、分词器行为变化）。
_DTC_RE = re.compile(r"\b[PUC][0-9A-F]{4}\b")


def _corpus_dtc_codes() -> set[str]:
    codes: set[str] = set()
    corpus_dir = Path(__file__).resolve().parent.parent / "seed" / "corpus"
    if not corpus_dir.is_dir():
        return codes
    for path in sorted(corpus_dir.iterdir()):
        if path.suffix not in {".json", ".md"}:
            continue
        try:
            codes.update(_DTC_RE.findall(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return codes


for _code in _corpus_dtc_codes():
    jieba.add_word(_code.lower(), freq=1000)

_TOKEN_CACHE: dict[str, list[str]] = {}

# 纯虚词与高频疑问词过滤：对 BM25 只贡献噪声分母（IDF 权重低但稀释头部区分度）。
# 只收功能词，领域词一律不进——"绝缘故障"等整词由 jieba 词典先行保护。
_STOPWORDS = frozenset(
    "的了是在和有与及对把被让给从向到就才都还又再也很挺更最没别想 "
    "怎么怎样为什么为何什么啥哪些哪里哪个多久多少是不是要不要应该该能可以会可能 "
    "出现发生今天现在突然忽然一直总是经常有时偶尔才能以后之后一般大概大约差不多 "
    "怎么办怎么样什么时候进行问题毛病".split()
)


def tokenize(text: str) -> list[str]:
    cached = _TOKEN_CACHE.get(text)
    if cached is not None:
        return cached
    lowered = text.lower()
    tokens = [
        t for t in jieba.lcut(lowered) if t.strip() and t not in _STOPWORDS
    ]
    if len(_TOKEN_CACHE) > 20_000:
        _TOKEN_CACHE.clear()
    _TOKEN_CACHE[text] = tokens
    return tokens


class Bm25Index:
    """kb_chunks 的内存 BM25 索引（含类别过滤所需的元数据）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._corpus_ids: list[int] = []
        self._corpus_meta: dict[int, tuple[str, str]] = {}  # id -> (category, doc_title)
        self._engine: BM25Okapi | None = None
        self._doc_tokens: dict[int, list[str]] = {}

    def rebuild(self, db: Session) -> None:
        rows = db.execute(
            select(KbChunk.id, KbChunk.content, KbDocument.category)
            .join(KbDocument, KbChunk.document_id == KbDocument.id)
        ).all()
        with self._lock:
            self._corpus_ids = []
            self._doc_tokens = {}
            self._corpus_meta = {}
            token_lists: list[list[str]] = []
            for chunk_id, content, category in rows:
                tokens = tokenize(content)
                self._corpus_ids.append(int(chunk_id))
                self._doc_tokens[int(chunk_id)] = tokens
                token_lists.append(tokens)
                self._corpus_meta[int(chunk_id)] = (category or "general", "")
            self._engine = BM25Okapi(token_lists) if token_lists else None

    def _ensure_loaded(self, db: Session) -> None:
        if self._engine is None:
            self.rebuild(db)

    def add(self, chunk_id: int, content: str, category: str) -> None:
        """增量加入新块（重建整表对万级数据也够快，但增量写路径更平滑）。"""
        with self._lock:
            if self._engine is None:
                return  # 未初始化时留给 rebuild
            tokens = tokenize(content)
            self._corpus_ids.append(int(chunk_id))
            self._doc_tokens[int(chunk_id)] = tokens
            self._corpus_meta[int(chunk_id)] = (category or "general", "")
            self._engine = BM25Okapi([self._doc_tokens[cid] for cid in self._corpus_ids])

    def remove(self, chunk_ids: list[int]) -> None:
        with self._lock:
            drop = set(chunk_ids)
            self._corpus_ids = [cid for cid in self._corpus_ids if cid not in drop]
            for cid in drop:
                self._doc_tokens.pop(cid, None)
                self._corpus_meta.pop(cid, None)
            self._engine = (
                BM25Okapi([self._doc_tokens[cid] for cid in self._corpus_ids])
                if self._corpus_ids
                else None
            )

    def search(
        self,
        db: Session,
        query: str,
        category: str | None = None,
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """返回 [(chunk_id, bm25_score)]，按分数降序。"""
        self._ensure_loaded(db)
        with self._lock:
            engine = self._engine
            if engine is None:
                return []
            scores = engine.get_scores(tokenize(query.lower()))
            pairs = sorted(
                zip(self._corpus_ids, scores), key=lambda p: p[1], reverse=True
            )
        if category:
            pairs = [p for p in pairs if self._corpus_meta.get(p[0], ("general", ""))[0] == category]
        return [(cid, float(s)) for cid, s in pairs[:top_k] if s > 0]


bm25_index = Bm25Index()
