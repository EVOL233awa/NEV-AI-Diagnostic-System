"""配置加载：data/config.json 是唯一配置源（含密钥，不进仓库、不下发前端）。

结构约定：
  server        = { host, port }
  deepseek      = { base_url, main_model, main_key, background_model, background_key }
  tavily        = { api_key }
  local_models  = { embedding_url, embedding_model, embedding_key, subagent_url, rerank_url }
                  embedding_key 非空时嵌入请求带 Bearer 认证（远端 OpenAI 兼容 API，如硅基流动）
  cors_origins  = [ ... ]           可选，缺省用 DEFAULT_CORS_ORIGINS
  security      = { jwt_secret }    首次启动自动生成并写回
  seed_admin    = { username, password } 首次初始化账号时写入（密码仅落此文件）
  superadmin    = { password }        superadmin 调试账号明文密码（与 API Key 同一密钥宿主；
                                      不进仓库/DB/接口响应；每次启动打印到后端终端窗口）
  agent         = { ... }           可选，Agent 运行参数（键缺省回退 AGENT_DEFAULTS；
                                    superadmin 后台在线修改，除 server/security 外均热生效）
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "data.db"
LOG_DIR = DATA_DIR / "logs"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

APP_TITLE = "新能源汽车 AI 智能诊断系统 2.0"
APP_VERSION = "2.0.0-alpha.0"

DEFAULT_CORS_ORIGINS = [
    "https://nev.evoidngc.top",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8600",
    "http://127.0.0.1:8600",
]

# Agent 运行参数（superadmin 后台可调；键缺省回退此处默认值）
AGENT_DEFAULTS: dict[str, Any] = {
    "max_tool_rounds": 6,            # 单轮用户消息允许的工具调用循环上限
    "max_ask_user": 3,               # 单轮 ask_user 提问上限
    "force_first_round_search": False,  # 首轮硬强制检索：API 层 tool_choice 锁定 kb_search
    "max_tokens": 2000,              # 主模型单次回复 token 上限
    "temperature": 0.6,              # 主模型采样温度
    "tool_result_max_chars": 4000,   # 单条工具结果截断
    "compress_max_rounds": 20,       # 阀门 1：保留最近轮数
    "compress_token_budget": 24000,  # 阀门 2：进上下文历史的估算 token 上限
    "compress_min_keep_rounds": 4,   # 阀门 2 触发时最少保留轮数
    "summary_max_chars": 800,        # 前情摘要长度约束
}

# 数字参数的合法区间（superadmin PUT 校验；越界拒绝而非钳制，避免静默改值）
AGENT_PARAM_RANGES: dict[str, tuple[int | float, int | float]] = {
    "max_tool_rounds": (1, 20),
    "max_ask_user": (0, 10),
    "max_tokens": (256, 32000),
    "temperature": (0.0, 2.0),
    "tool_result_max_chars": (500, 30000),
    "compress_max_rounds": (2, 100),
    "compress_token_budget": (4000, 200000),
    "compress_min_keep_rounds": (1, 20),
    "summary_max_chars": (200, 4000),
}


@dataclass
class Settings:
    host: str
    port: int
    cors_origins: list[str]
    jwt_secret: str
    raw: dict[str, Any]

    @property
    def deepseek(self) -> dict[str, Any]:
        return self.raw.get("deepseek", {})

    @property
    def tavily(self) -> dict[str, Any]:
        return self.raw.get("tavily", {})

    @property
    def local_models(self) -> dict[str, Any]:
        return self.raw.get("local_models", {})

    @property
    def seed_admin(self) -> dict[str, Any]:
        return self.raw.get("seed_admin", {})

    @property
    def agent(self) -> dict[str, Any]:
        return self.raw.get("agent", {})


def agent_param(key: str) -> int | float | bool:
    """Agent 运行参数热读取：config.json agent 节优先，缺省回退 AGENT_DEFAULTS。

    每次调用实时读 settings（settings.raw 是启动时加载的同一 dict 对象，
    superadmin PUT 直接改它），改配置即生效、无需重启。
    """
    value = settings.agent.get(key, AGENT_DEFAULTS.get(key))
    return value if value is not None else AGENT_DEFAULTS.get(key)  # type: ignore[return-value]


def load_raw() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"缺少配置文件 {CONFIG_PATH}——请先创建（含 server/deepseek/tavily/local_models 各节，密钥只放这里）"
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_raw(raw: dict[str, Any]) -> None:
    """把变更（jwt_secret / seed_admin 等非代码配置）写回 config.json，保留其余键。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _ensure_jwt_secret(raw: dict[str, Any]) -> str:
    sec = raw.get("security")
    if isinstance(sec, dict) and sec.get("jwt_secret"):
        return str(sec["jwt_secret"])
    token = secrets.token_urlsafe(48)
    sec = dict(sec) if isinstance(sec, dict) else {}
    sec["jwt_secret"] = token
    raw["security"] = sec
    save_raw(raw)
    return token


def load_settings() -> Settings:
    raw = load_raw()
    server = raw.get("server", {})
    return Settings(
        host=str(server.get("host", "127.0.0.1")),
        port=int(server.get("port", 8600)),
        cors_origins=list(raw.get("cors_origins", DEFAULT_CORS_ORIGINS)),
        jwt_secret=_ensure_jwt_secret(raw),
        raw=raw,
    )


settings = load_settings()
