"""pytest 全局夹具：独立临时 SQLite 库与临时 config.json，绝不触碰 data/ 真实文件。

时机关键：engine 以值拷贝绑定 config.DB_PATH（backend/db/base.py 顶部
`from backend.config import DB_PATH`），必须在 backend.db.base 首次 import
之前改写 backend.config.DB_PATH —— 本文件顶层即做，pytest 保证 conftest
先于测试模块加载。config.json 同理隔离：superadmin 配置读写用例会真实
save_raw()，绝不能落到真实 data/config.json。种子（账号 + 演示车）落在临时库，
测试完全离线。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

import backend.config as backend_config

_TMP_DIR = Path(tempfile.mkdtemp(prefix="nev-diag-test-"))
backend_config.DB_PATH = _TMP_DIR / "test.db"
backend_config.CONFIG_PATH = _TMP_DIR / "config.json"
backend_config.CONFIG_PATH.write_text(
    json.dumps({"server": {"host": "127.0.0.1", "port": 8600}}), encoding="utf-8"
)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.db.base import SessionLocal  # noqa: E402


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    app = create_app()
    # BM25 语料垫底：rank_bm25 在极小语料上全词 IDF 为负 → 得分全 0；
    # 灌几篇与中文查询无交集的英文噪声文档，保证测试内检索行为与生产（300+ 块）一致
    class _NoiseEmbedder:
        dim = 1024

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.03] * self.dim for _ in texts]

    from backend.rag import ingest

    db = SessionLocal()
    try:
        for i in range(4):
            body = f"Lorem ipsum dolor sit amet {i}, consectetur adipiscing elit, sed do eiusmod tempor incididunt."
            body += f" Ut enim ad minim veniam {i * 7}, quis nostrud exercitation ullamco laboris nisi ut aliquip."
            ingest.ingest_document(
                db, title=f"noise-{i}", category="general", markdown_text=f"# Noise {i}\n{body}\n",
                embedder=_NoiseEmbedder(),
            )
    finally:
        db.close()
    with TestClient(app) as c:
        yield c


def login_headers(client: TestClient, username: str) -> dict[str, str]:
    """种子账号密码 = 账号名（seed.py 裁定）；只在运行时使用，不打印。"""
    r = client.post("/api/auth/login", json={"username": username, "password": username})
    assert r.status_code == 200, f"登录失败 {username}: HTTP {r.status_code}"
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def owner_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, "user001")


@pytest.fixture(scope="session")
def staff_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, "staff001")


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, "admin")


@pytest.fixture
def db_session(client):
    """独立 DB 会话（每测试一个）；依赖 client 确保临时库已建表+种子。"""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
