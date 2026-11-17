"""配置加载：data/config.json 是唯一配置源（含密钥，不进仓库、不下发前端）。

结构约定（schema_version = 2，v2.1.0 起）：
  server        = { host, port }
  deepseek      = { base_url, main_model, main_key, aux_key }
                  aux_key 供压缩/标题/抽取等辅助任务使用，空则回退 main_key
  local_models  = { embedding_url, embedding_model, embedding_key, rerank_url,
                    rerank_key, rerank_enabled, rerank_model, rerank_score_threshold }
                  embedding_key 非空时嵌入请求带 Bearer 认证（远端 OpenAI 兼容 API，如硅基流动）
  search        = { provider, fallback_to_tavily, fallback_on_empty, count,
                    content_max_chars, deepseek{...}, tavily{...}, custom{...} }
                  联网检索供应商（deepseek 官方默认，tavily/custom 可切换）
  asr           = { provider, max_seconds, max_bytes, deepseek{...}, openai{...} }
                  语音转文字供应商（deepseek 官方默认，openai 兼容接口可切换）
  quota         = { asr_daily_seconds_per_user, search_daily_calls_per_user, global_daily_usd }
                  三值 null/缺失/空串/0 = 不限制；正数 = 当日上限
  cors_origins  = [ ... ]           可选，缺省用 DEFAULT_CORS_ORIGINS
  security      = { jwt_secret }    首次启动自动生成并写回
  seed_admin    = { username, password } 首次初始化账号时写入（密码仅落此文件）
  superadmin    = { password, password_source }
                  superadmin 调试账号明文密码与来源（env/config/generated）；
                  不进仓库/DB/接口响应；仅首次生成时打印到终端，env/config 来源不回显
  agent         = { ... }           可选，Agent 运行参数（键缺省回退 AGENT_DEFAULTS；
                                    superadmin 后台在线修改，除 server/security 外均热生效）
  _meta         = { schema_version } 配置结构版本（迁移判据）

v2.0.x 旧配置（small_model / deepseek.background_* / local_models.subagent_url / tavily）
在首次启动时自动迁移并备份为 data/config.json.bak-YYYYmmddHHMMSS。
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
# 测试/多实例可用 NEV_CONFIG_PATH 指向隔离配置；默认仍是 data/config.json
CONFIG_PATH = Path(os.environ.get("NEV_CONFIG_PATH") or (DATA_DIR / "config.json"))
DB_PATH = DATA_DIR / "data.db"
LOG_DIR = DATA_DIR / "logs"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

APP_TITLE = "新能源汽车 AI 智能诊断系统 2.1"
APP_VERSION = "2.1.0"

SCHEMA_VERSION = 2

DEFAULT_CORS_ORIGINS = [
    "https://nev.evoidngc.top",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8600",
    "http://127.0.0.1:8600",
]

DEEPSEEK_OFFICIAL_HOST = "api.deepseek.com"

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
    # 辅助任务（标题/状态卡抽取，走主模型 + aux key）
    "title_temperature": 0.2,
    "title_max_tokens": 60,
    "title_input_chars": 500,
    "extract_temperature": 0.0,
    "extract_max_tokens": 300,
    "extract_input_chars": 800,
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
    "title_temperature": (0.0, 2.0),
    "title_max_tokens": (16, 512),
    "title_input_chars": (50, 2000),
    "extract_temperature": (0.0, 2.0),
    "extract_max_tokens": (50, 2000),
    "extract_input_chars": (100, 8000),
}

# 重排参数（local_models 节，superadmin PUT 校验区间；score_threshold 实测评见 rag/reranker.py）
RERANK_PARAM_RANGES: dict[str, tuple[int | float, int | float]] = {
    "rerank_score_threshold": (0.0, 1.0),
}

DEFAULT_SEARCH: dict[str, Any] = {
    "provider": "deepseek",
    "fallback_to_tavily": True,
    "fallback_on_empty": False,
    "count": 5,
    "content_max_chars": 1200,
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "need_content": True,
        "dynamic_language": True,
        "timeout": 20,
    },
    "tavily": {
        "api_key": "",
        "search_depth": "basic",
        "max_results": 5,
        "timeout": 20,
    },
    "custom": {
        "base_url": "",
        "api_key": "",
        "timeout": 20,
    },
}

DEFAULT_ASR: dict[str, Any] = {
    "provider": "deepseek",
    "max_seconds": 120,
    "max_bytes": 8388608,
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "timeout": 60,
    },
    "openai": {
        "base_url": "",
        "api_key": "",
        "model": "whisper-1",
        "timeout": 60,
    },
}

DEFAULT_QUOTA: dict[str, Any] = {
    "asr_daily_seconds_per_user": None,
    "search_daily_calls_per_user": None,
    "global_daily_usd": None,
}


def _deep_merge(defaults: dict[str, Any], value: Any) -> dict[str, Any]:
    """默认值垫底深合并：缺失键补默认，已有值原样保留。"""
    result = deepcopy(defaults)
    if not isinstance(value, dict):
        return result
    for key, item in value.items():
        if isinstance(item, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], item)
        else:
            result[key] = item
    return result


def _apply_defaults(raw: dict[str, Any]) -> None:
    """补齐 search/asr/quota/deepseek.aux_key 等结构默认值（不改已有值）。"""
    ds = raw.setdefault("deepseek", {})
    if not isinstance(ds, dict):
        ds = {}
        raw["deepseek"] = ds
    ds.setdefault("aux_key", "")
    raw["search"] = _deep_merge(DEFAULT_SEARCH, raw.get("search"))
    raw["asr"] = _deep_merge(DEFAULT_ASR, raw.get("asr"))
    raw["quota"] = _deep_merge(DEFAULT_QUOTA, raw.get("quota"))
    raw.setdefault("local_models", {})
    raw.setdefault("agent", {})


def is_official_deepseek(base_url: str) -> bool:
    """base_url 是否指向 DeepSeek 官方（子路径带不带 /v1 均可）。

    只有官方端点才允许「专用 key 留空 → 回退主模型 key」，避免主模型换供应商后
    把主 key 打到别家端点。
    """
    raw = (base_url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw if "//" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower() == DEEPSEEK_OFFICIAL_HOST


def _config_backup_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.bak-{stamp}")


def _append_migration_log(lines: list[str]) -> None:
    if not lines:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "migration.log", "a", encoding="utf-8") as f:
            stamp = datetime.now().isoformat(timespec="seconds")
            for line in lines:
                f.write(f"[{stamp}] {line}\n")
    except OSError as exc:
        # 迁移日志是旁路观测，写不进去不能让已迁移的配置启动失败
        print(f"[config] 迁移日志写入失败（不影响启动）：{exc}")


def _migrate_config(raw: dict[str, Any]) -> None:
    """v2.0.x → v2 结构迁移：备份 → 重排键 → 写回；异常向上抛，不吞半迁移。"""
    meta = raw.get("_meta")
    try:
        version = int(meta.get("schema_version") or 0) if isinstance(meta, dict) else 0
    except (TypeError, ValueError):
        version = 0
    if version >= SCHEMA_VERSION:
        return

    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, _config_backup_path())

    warnings: list[str] = []
    had_search = isinstance(raw.get("search"), dict)
    had_asr = isinstance(raw.get("asr"), dict)

    # 1) small_model 槽位移除：标题/抽取参数迁入 agent，api_key 不自动迁移
    small_model = raw.pop("small_model", None)
    if isinstance(small_model, dict):
        if small_model.get("base_url") or small_model.get("model"):
            warnings.append("small_model 已移除，标题/抽取改走主模型")
        agent = raw.setdefault("agent", {})
        if not isinstance(agent, dict):
            agent = {}
            raw["agent"] = agent
        for key in ("title_temperature", "title_max_tokens", "title_input_chars",
                    "extract_temperature", "extract_max_tokens", "extract_input_chars"):
            if key not in agent and small_model.get(key) is not None:
                agent[key] = small_model[key]

    # 2) background_* → aux_key（同模型、独立 key），其余键删除
    ds = raw.get("deepseek")
    if isinstance(ds, dict):
        background_key = str(ds.get("background_key") or "")
        if background_key and not str(ds.get("aux_key") or ""):
            ds["aux_key"] = background_key
            warnings.append("deepseek.background_key 已迁移为 deepseek.aux_key")
        for key in ("background_base_url", "background_model", "background_key"):
            ds.pop(key, None)

    # 3) 死配置 subagent_url 移除
    lm = raw.get("local_models")
    if isinstance(lm, dict):
        lm.pop("subagent_url", None)

    # 4) 旧 tavily 节 → search.tavily
    legacy_tavily = raw.pop("tavily", None)
    if isinstance(legacy_tavily, dict) and legacy_tavily.get("api_key") and not isinstance(raw.get("search"), dict):
        raw["search"] = {"tavily": {"api_key": legacy_tavily["api_key"]}}
    elif isinstance(legacy_tavily, dict) and legacy_tavily.get("api_key"):
        search = raw.setdefault("search", {})
        tavily = search.setdefault("tavily", {})
        if not tavily.get("api_key"):
            tavily["api_key"] = legacy_tavily["api_key"]

    # 5) search / asr / quota 默认值；DeepSeek 端点只在原 base_url 为官方时继承，
    #    非官方主模型供应商下留空（专用 key 不跨供应商复用，等待部署者显式配置）
    _apply_defaults(raw)
    ds = raw.get("deepseek", {})
    official = isinstance(ds, dict) and is_official_deepseek(str(ds.get("base_url") or ""))
    search = raw.get("search", {})
    asr = raw.get("asr", {})
    if not had_search and isinstance(search.get("deepseek"), dict):
        search["deepseek"]["base_url"] = str(ds.get("base_url") or "").rstrip("/") if official else ""
    if not had_asr and isinstance(asr.get("deepseek"), dict):
        asr["deepseek"]["base_url"] = str(ds.get("base_url") or "").rstrip("/") if official else ""

    raw["_meta"] = {**(meta if isinstance(meta, dict) else {}), "schema_version": SCHEMA_VERSION}
    save_raw(raw)
    _append_migration_log(warnings)


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
    def search(self) -> dict[str, Any]:
        return self.raw.get("search", {})

    @property
    def asr(self) -> dict[str, Any]:
        return self.raw.get("asr", {})

    @property
    def quota(self) -> dict[str, Any]:
        return self.raw.get("quota", {})

    @property
    def local_models(self) -> dict[str, Any]:
        return self.raw.get("local_models", {})

    @property
    def seed_admin(self) -> dict[str, Any]:
        return self.raw.get("seed_admin", {})

    @property
    def agent(self) -> dict[str, Any]:
        return self.raw.get("agent", {})

    @property
    def superadmin(self) -> dict[str, Any]:
        return self.raw.get("superadmin", {})


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
            f"缺少配置文件 {CONFIG_PATH}——请先创建（含 server/deepseek/local_models/security 各节，密钥只放这里）"
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_raw(raw: dict[str, Any]) -> None:
    """把变更（jwt_secret / seed_admin 等非代码配置）原子写回 config.json。

    先写同目录临时文件并 fsync，再 os.replace 覆盖；进程中途崩溃/磁盘满不会留下
    被截断的密钥配置。Windows 上 os.replace 可原子覆盖已存在文件。
    """
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_PATH)
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except OSError:
            pass  # Windows 上 chmod 语义有限，失败不影响写入
    except BaseException:
        # 失败时清掉半成品临时文件，原 config.json 保持上一版完整内容
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


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
    # 测试夹具在导入前置位：临时 config 不触发迁移（避免污染真实 data/config.json）
    if os.environ.get("NEV_SKIP_CONFIG_MIGRATION") != "1":
        _migrate_config(raw)
    else:
        _apply_defaults(raw)
    server = raw.get("server", {})
    return Settings(
        host=str(server.get("host", "127.0.0.1")),
        port=int(server.get("port", 8600)),
        cors_origins=list(raw.get("cors_origins", DEFAULT_CORS_ORIGINS)),
        jwt_secret=_ensure_jwt_secret(raw),
        raw=raw,
    )


settings = load_settings()
