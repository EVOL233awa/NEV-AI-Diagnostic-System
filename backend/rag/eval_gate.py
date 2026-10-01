"""检索评测红绿验证。

绿：当前检索引擎在评测集上 top3 命中率 ≥ GREEN_THRESHOLD。
红：注入故障模式（向量主路失效降级 BM25 / 嵌入随机化 / 打乱排序）后指标必须显著下降，
    证明评测集真实约束检索逻辑（改坏必见红），而非恒过。

用法：D:/Python/python.exe -m backend.rag.eval_gate [--corpus-dir backend/seed/corpus]
退出码：0 = 绿 + 全部故障模式见红；1 = 未达标。
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from backend.config import BASE_DIR
from backend.db.base import SessionLocal, init_db
from backend.rag import retrieve

GREEN_THRESHOLD = 0.80  # top3 命中率门槛
RED_DROP = 0.15  # 故障模式相对绿基线至少下降的幅度
EVAL_PATH = Path(BASE_DIR) / "backend" / "seed" / "corpus" / "eval_set.json"


def load_cases() -> list[dict]:
    with open(EVAL_PATH, encoding="utf-8") as f:
        return json.load(f)["cases"]


def run_eval(db: SessionLocal, cases: list[dict], fault: str | None = None) -> float:
    hits = 0
    for case in cases:
        results = _search_with_fault(db, case["query"], fault)
        for r in results[:3]:
            if case["doc_key"] in r.document_title or case["sec_key"] in r.section_path:
                hits += 1
                break
    return hits / len(cases) if cases else 0.0


def _search_with_fault(db: SessionLocal, query: str, fault: str | None):
    if fault is None:
        return retrieve.search(db, query, top_k=5)
    if fault == "bm25_only":
        # 破坏向量路：让嵌入请求失败
        class _BrokenEmbedder:
            def embed(self, texts: list[str]) -> list[list[float]]:
                raise retrieve.EmbedderUnavailable("fault injection")

        return retrieve.search(db, query, top_k=5, embedder=_BrokenEmbedder())
    if fault == "vec_only":
        # 破坏关键词路：注入空 BM25 索引
        original = retrieve.bm25_index
        retrieve.bm25_index = _EmptyIndex()
        try:
            return retrieve.search(db, query, top_k=5)
        finally:
            retrieve.bm25_index = original
    if fault == "vec_noise":
        # 破坏向量质量：注入固定种子的随机嵌入，证明精度由向量检索承载而非候选集运气
        rng = random.Random(42)

        class _NoisyEmbedder:
            def embed(self, texts: list[str]) -> list[list[float]]:
                return [
                    [rng.uniform(-1.0, 1.0) for _ in range(retrieve.vecstore.EMBED_DIM)]
                    for _ in texts
                ]

        return retrieve.search(db, query, top_k=5, embedder=_NoisyEmbedder())
    if fault == "shuffle":
        results = retrieve.search(db, query, top_k=20)
        random.Random(20260930).shuffle(results)  # 固定种子：闸门判定必须可复现
        return results
    raise ValueError(f"unknown fault: {fault}")


class _EmptyIndex:
    def search(self, *_args, **_kwargs):
        return []

    def add(self, *_a, **_k):
        return None

    def remove(self, *_a, **_k):
        return None

    def rebuild(self, *_a, **_k):
        return None


def main() -> int:
    init_db()
    db = SessionLocal()
    cases = load_cases()
    try:
        baseline = run_eval(db, cases)
        print(f"[green] baseline top3 hit-rate = {baseline:.2%} (threshold {GREEN_THRESHOLD:.0%})")
        if baseline < GREEN_THRESHOLD:
            print("[FAIL] 基线未达绿线")
            _print_misses(db, cases)
            return 1

        ok = True
        # 必见红（恒过即闸门失效，改坏必暴露）：
        #   bm25_only：向量主路失效 → 降级保底路径接管。既证明向量路真实贡献精度，
        #     也检验保底路径本身可用（嵌入服务挂掉时检索不能崩）。
        #   vec_noise：注入固定种子的随机嵌入——证明精度由向量检索承载，而非候选集运气。
        #   shuffle：固定种子打乱 top20——证明排序逻辑真实生效，判定可复现。
        # 旧 vec_only（禁 BM25）随向量主路切换取消：健康路径已不跑 BM25，该模式与基线重合无信息量。
        for fault in ("bm25_only", "vec_noise", "shuffle"):
            score = run_eval(db, cases, fault=fault)
            drop = round(baseline - score, 4)
            status = "RED ok" if drop >= RED_DROP else "NOT RED"
            print(f"[red] fault={fault}: {score:.2%} (drop {drop:.2%}) -> {status}")
            if drop < RED_DROP:
                ok = False
        if not ok:
            print("[FAIL] 存在故障模式未见红——评测集约束力不足")
            return 1
        print("[PASS] 检索红绿验证通过")
        return 0
    finally:
        db.close()


def _print_misses(db: SessionLocal, cases: list[dict]) -> None:
    for case in cases:
        results = _search_with_fault(db, case["query"], None)
        hit = any(
            case["doc_key"] in r.document_title or case["sec_key"] in r.section_path
            for r in results[:3]
        )
        if not hit:
            tops = [(r.document_title[:16], r.section_path[:20]) for r in results[:3]]
            print(f"  MISS: {case['query']} -> {tops}")


if __name__ == "__main__":
    sys.exit(main())
