"""superadmin 调试后台：供应商、搜索、ASR、限额与 Agent 运行参数在线配置。

定位类似 AstrBot WebUI 的供应商配置页，仅供部署者本人调试使用：
- 读写 data/config.json（密钥唯一宿主）：改完即落盘，运行中进程热生效
  （provider/embedder/搜索/ASR/压缩/循环参数均为每次调用实时读取；server/security 除外）。
- 密钥单向模糊：GET 只回掩码，PUT 留空/缺省 = 保持原值，显式 "__clear__" 才清除。
- 全部接口 require_roles("superadmin")；admin 不可见（admin_users 已隔离）。
- superadmin 密码来源（env/config/generated）只读展示；修改密码走 PUT /password。
"""
from __future__ import annotations

import math
import os
import time
from copy import deepcopy
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.deps import DbSession, require_roles
from backend.api.auth import ensure_password_strength
from backend.config import (
    AGENT_DEFAULTS,
    AGENT_PARAM_RANGES,
    APP_VERSION,
    RERANK_PARAM_RANGES,
    save_raw,
    settings,
)
from backend.core.providers.llm import get_aux_provider, get_main_provider
from backend.db.models import AuditLog, User
from backend.rag.reranker import rerank_api
from backend.security import hash_password
from backend.seed.seed import SUPERADMIN_ENV_VAR, SUPERADMIN_USERNAME

router = APIRouter(prefix="/api/superadmin", tags=["superadmin"])

# PUT 里 api_key 传空串视同「不修改」：真要吊销 key 可显式传 "__clear__"
CLEAR_KEY = "__clear__"

QUOTA_FIELDS = ("asr_daily_seconds_per_user", "search_daily_calls_per_user", "global_daily_usd")


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


class ProviderUpsert(BaseModel):
    base_url: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=512)
    aux_key: str | None = Field(default=None, max_length=512)


class RerankUpsert(BaseModel):
    """重排配置（local_models 节）。数值 None = 不修改；区间校验见 RERANK_PARAM_RANGES。"""

    enabled: bool | None = None
    url: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=128)
    api_key: str | None = Field(default=None, max_length=512)  # 空 = 回落 embedding_key
    score_threshold: float | None = None


class DeepSeekSearchIn(BaseModel):
    base_url: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=512)
    need_content: bool | None = None
    dynamic_language: bool | None = None
    timeout: float | None = Field(default=None, gt=0, le=300)


class TavilySearchIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=512)
    search_depth: Literal["basic", "advanced"] | None = None
    max_results: int | None = Field(default=None, ge=1, le=10)
    timeout: float | None = Field(default=None, gt=0, le=300)


class CustomSearchIn(BaseModel):
    base_url: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=512)
    timeout: float | None = Field(default=None, gt=0, le=300)


class SearchIn(BaseModel):
    provider: Literal["deepseek", "tavily", "custom"] | None = None
    fallback_to_tavily: bool | None = None
    fallback_on_empty: bool | None = None
    count: int | None = Field(default=None, ge=1, le=10)
    content_max_chars: int | None = Field(default=None, ge=200, le=8000)
    deepseek: DeepSeekSearchIn | None = None
    tavily: TavilySearchIn | None = None
    custom: CustomSearchIn | None = None


class AsrDeepSeekIn(BaseModel):
    base_url: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=512)
    timeout: float | None = Field(default=None, gt=0, le=300)


class AsrOpenAIIn(BaseModel):
    base_url: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)
    timeout: float | None = Field(default=None, gt=0, le=300)


class AsrIn(BaseModel):
    provider: Literal["deepseek", "openai"] | None = None
    max_seconds: int | None = Field(default=None, ge=5, le=600)
    max_bytes: int | None = Field(default=None, ge=1_048_576, le=16_777_216)
    deepseek: AsrDeepSeekIn | None = None
    openai: AsrOpenAIIn | None = None


class QuotaIn(BaseModel):
    """None/0 = 不限制；负值/非有限数在 apply 阶段拒绝。字段缺省 = 不修改。"""

    asr_daily_seconds_per_user: float | None = None
    search_daily_calls_per_user: float | None = None
    global_daily_usd: float | None = None


class ProvidersIn(BaseModel):
    main: ProviderUpsert | None = None
    embedding: ProviderUpsert | None = None
    rerank: RerankUpsert | None = None


class AgentIn(BaseModel):
    """数值 None = 不修改；bool 直接覆盖。范围校验见 AGENT_PARAM_RANGES。"""

    max_tool_rounds: int | None = None
    max_ask_user: int | None = None
    force_first_round_search: bool | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    tool_result_max_chars: int | None = None
    compress_max_rounds: int | None = None
    compress_token_budget: int | None = None
    compress_min_keep_rounds: int | None = None
    summary_max_chars: int | None = None
    title_temperature: float | None = None
    title_max_tokens: int | None = None
    title_input_chars: int | None = None
    extract_temperature: float | None = None
    extract_max_tokens: int | None = None
    extract_input_chars: int | None = None


class ConfigIn(BaseModel):
    providers: ProvidersIn | None = None
    search: SearchIn | None = None
    asr: AsrIn | None = None
    quota: QuotaIn | None = None
    agent: AgentIn | None = None


class TestIn(BaseModel):
    slot: Literal["main", "aux", "background", "embedding", "rerank", "search", "web_search"]


class SearchTestIn(BaseModel):
    provider: Literal["deepseek", "tavily", "custom"] | None = None
    query: str = Field(default="新能源汽车 动力电池 故障", max_length=100)


class PasswordIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


def _password_source() -> str:
    source = str(settings.superadmin.get("password_source") or "").strip()
    if source in ("env", "config", "generated"):
        return source
    return "config" if settings.superadmin.get("password") else "generated"


def _provider_view() -> dict[str, Any]:
    ds = settings.deepseek
    lm = settings.local_models
    return {
        "main": {
            "base_url": str(ds.get("base_url", "")),
            "model": str(ds.get("main_model", "")),
            "has_key": bool(ds.get("main_key")),
            "key_masked": _mask(str(ds.get("main_key") or "")),
            "aux_has_key": bool(ds.get("aux_key")),
            "aux_key_masked": _mask(str(ds.get("aux_key") or "")),
            "aux_effective": bool(ds.get("aux_key") or ds.get("main_key")),
        },
        "embedding": {
            "base_url": str(lm.get("embedding_url", "")),
            "model": str(lm.get("embedding_model", "")),
            "has_key": bool(lm.get("embedding_key")),
            "key_masked": _mask(str(lm.get("embedding_key") or "")),
        },
        "rerank": {
            "enabled": bool(lm.get("rerank_enabled", True)),
            "url": str(lm.get("rerank_url", "")),
            "model": str(lm.get("rerank_model", "")),
            "score_threshold": float(lm.get("rerank_score_threshold") or 0.0),
            "has_key": bool(lm.get("rerank_key") or lm.get("embedding_key")),
            "key_masked": _mask(str(lm.get("rerank_key") or lm.get("embedding_key") or "")),
        },
    }


def _search_view() -> dict[str, Any]:
    search = settings.search
    ds = search.get("deepseek") if isinstance(search.get("deepseek"), dict) else {}
    tv = search.get("tavily") if isinstance(search.get("tavily"), dict) else {}
    cu = search.get("custom") if isinstance(search.get("custom"), dict) else {}
    return {
        "provider": str(search.get("provider") or "deepseek"),
        "fallback_to_tavily": bool(search.get("fallback_to_tavily")),
        "fallback_on_empty": bool(search.get("fallback_on_empty")),
        "count": int(search.get("count") or 5),
        "content_max_chars": int(search.get("content_max_chars") or 1200),
        "deepseek": {
            "base_url": str(ds.get("base_url", "")),
            "has_key": bool(ds.get("api_key")),
            "key_masked": _mask(str(ds.get("api_key") or "")),
            "need_content": bool(ds.get("need_content", True)),
            "dynamic_language": bool(ds.get("dynamic_language", True)),
            "timeout": float(ds.get("timeout") or 20),
        },
        "tavily": {
            "has_key": bool(tv.get("api_key")),
            "key_masked": _mask(str(tv.get("api_key") or "")),
            "search_depth": str(tv.get("search_depth") or "basic"),
            "max_results": int(tv.get("max_results") or 5),
            "timeout": float(tv.get("timeout") or 20),
        },
        "custom": {
            "base_url": str(cu.get("base_url", "")),
            "has_key": bool(cu.get("api_key")),
            "key_masked": _mask(str(cu.get("api_key") or "")),
            "timeout": float(cu.get("timeout") or 20),
        },
    }


def _asr_view() -> dict[str, Any]:
    asr = settings.asr
    ds = asr.get("deepseek") if isinstance(asr.get("deepseek"), dict) else {}
    oa = asr.get("openai") if isinstance(asr.get("openai"), dict) else {}
    return {
        "provider": str(asr.get("provider") or "deepseek"),
        "max_seconds": int(asr.get("max_seconds") or 120),
        "max_bytes": int(asr.get("max_bytes") or 8388608),
        "deepseek": {
            "base_url": str(ds.get("base_url", "")),
            "has_key": bool(ds.get("api_key")),
            "key_masked": _mask(str(ds.get("api_key") or "")),
            "timeout": float(ds.get("timeout") or 60),
        },
        "openai": {
            "base_url": str(oa.get("base_url", "")),
            "model": str(oa.get("model", "")),
            "has_key": bool(oa.get("api_key")),
            "key_masked": _mask(str(oa.get("api_key") or "")),
            "timeout": float(oa.get("timeout") or 60),
        },
    }


def _quota_view() -> dict[str, Any]:
    return {key: settings.quota.get(key) for key in QUOTA_FIELDS}


def _agent_view() -> dict[str, Any]:
    configured = settings.agent
    return {key: configured.get(key, default) for key, default in AGENT_DEFAULTS.items()}


@router.get("/config")
def get_config(user: User = Depends(require_roles("superadmin"))) -> dict:
    return {
        "providers": _provider_view(),
        "search": _search_view(),
        "asr": _asr_view(),
        "quota": _quota_view(),
        "agent": _agent_view(),
        "superadmin": {
            "password_source": _password_source(),
            "password_set": bool(settings.superadmin.get("password")),
        },
        "server": {
            "host": settings.host,
            "port": settings.port,
            "version": APP_VERSION,
            # 这些键改了要重启进程才生效（其余全部热生效）
            "restart_required_keys": ["server.host", "server.port", "cors_origins", "security.jwt_secret"],
        },
    }


def _apply_key(section: dict[str, Any], field: str, value: str | None, touched: list[str]) -> None:
    """密钥语义：None/空串 = 保持；__clear__ = 清除；其他 = 覆盖。"""
    if value is None or value == "":
        return
    if value == CLEAR_KEY:
        section[field] = ""
        touched.append(field)
        return
    section[field] = value.strip()
    touched.append(field)


def _apply_provider(
    section: dict[str, Any],
    upsert: ProviderUpsert,
    key_field: str,
    url_field: str = "base_url",
    model_field: str | None = None,
    key_prefix: str = "",
) -> list[str]:
    touched: list[str] = []
    if upsert.base_url is not None:
        section[url_field] = upsert.base_url.strip()
        touched.append(url_field)
    if upsert.model is not None and model_field:
        section[model_field] = upsert.model.strip()
        touched.append(model_field)
    _apply_key(section, key_field, upsert.api_key, touched)
    # 前缀只用于区分同名 key（embedding_key），url/model 已是唯一键名
    return [(key_prefix + t) if t == key_field else t for t in touched]


def _apply_providers(body: ProvidersIn) -> list[str]:
    raw = settings.raw
    ds = raw.setdefault("deepseek", {})
    lm = raw.setdefault("local_models", {})
    touched: list[str] = []
    if body.main is not None:
        touched += _apply_provider(ds, body.main, "main_key", model_field="main_model")
        if body.main.aux_key is not None:
            aux_touched: list[str] = []
            _apply_key(ds, "aux_key", body.main.aux_key, aux_touched)
            touched += aux_touched
    if body.embedding is not None:
        touched += _apply_provider(
            lm, body.embedding, "embedding_key", url_field="embedding_url",
            model_field="embedding_model", key_prefix="embedding.",
        )
    if body.rerank is not None:
        touched += _apply_rerank(body.rerank, lm)
    return touched


def _apply_rerank(body: RerankUpsert, lm: dict[str, Any]) -> list[str]:
    touched: list[str] = []
    if body.enabled is not None:
        lm["rerank_enabled"] = bool(body.enabled)
        touched.append("rerank_enabled")
    if body.url is not None:
        lm["rerank_url"] = body.url.strip()
        touched.append("rerank_url")
    if body.model is not None:
        lm["rerank_model"] = body.model.strip()
        touched.append("rerank_model")
    _apply_key(lm, "rerank_key", body.api_key, touched)
    if body.score_threshold is not None:
        lo, hi = RERANK_PARAM_RANGES["rerank_score_threshold"]
        if not lo <= body.score_threshold <= hi:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"rerank.score_threshold 超出合法区间 [{lo}, {hi}]",
            )
        lm["rerank_score_threshold"] = body.score_threshold
        touched.append("rerank_score_threshold")
    return touched


def _apply_search(body: SearchIn) -> list[str]:
    search = settings.raw.setdefault("search", {})
    touched: list[str] = []
    if body.provider is not None:
        search["provider"] = body.provider
        touched.append("search.provider")
    for field in ("fallback_to_tavily", "fallback_on_empty"):
        value = getattr(body, field)
        if value is not None:
            search[field] = bool(value)
            touched.append(f"search.{field}")
    for field in ("count", "content_max_chars"):
        value = getattr(body, field)
        if value is not None:
            search[field] = value
            touched.append(f"search.{field}")
    if body.deepseek is not None:
        section = search.setdefault("deepseek", {})
        if body.deepseek.base_url is not None:
            section["base_url"] = body.deepseek.base_url.strip()
            touched.append("search.deepseek.base_url")
        if body.deepseek.need_content is not None:
            section["need_content"] = bool(body.deepseek.need_content)
            touched.append("search.deepseek.need_content")
        if body.deepseek.dynamic_language is not None:
            section["dynamic_language"] = bool(body.deepseek.dynamic_language)
            touched.append("search.deepseek.dynamic_language")
        if body.deepseek.timeout is not None:
            section["timeout"] = body.deepseek.timeout
            touched.append("search.deepseek.timeout")
        key_touched: list[str] = []
        _apply_key(section, "api_key", body.deepseek.api_key, key_touched)
        touched += [f"search.deepseek.{k}" for k in key_touched]
    if body.tavily is not None:
        section = search.setdefault("tavily", {})
        if body.tavily.search_depth is not None:
            section["search_depth"] = body.tavily.search_depth
            touched.append("search.tavily.search_depth")
        if body.tavily.max_results is not None:
            section["max_results"] = body.tavily.max_results
            touched.append("search.tavily.max_results")
        if body.tavily.timeout is not None:
            section["timeout"] = body.tavily.timeout
            touched.append("search.tavily.timeout")
        key_touched = []
        _apply_key(section, "api_key", body.tavily.api_key, key_touched)
        touched += [f"search.tavily.{k}" for k in key_touched]
    if body.custom is not None:
        section = search.setdefault("custom", {})
        if body.custom.base_url is not None:
            section["base_url"] = body.custom.base_url.strip()
            touched.append("search.custom.base_url")
        if body.custom.timeout is not None:
            section["timeout"] = body.custom.timeout
            touched.append("search.custom.timeout")
        key_touched = []
        _apply_key(section, "api_key", body.custom.api_key, key_touched)
        touched += [f"search.custom.{k}" for k in key_touched]
    return touched


def _apply_asr(body: AsrIn) -> list[str]:
    asr = settings.raw.setdefault("asr", {})
    touched: list[str] = []
    if body.provider is not None:
        asr["provider"] = body.provider
        touched.append("asr.provider")
    for field in ("max_seconds", "max_bytes"):
        value = getattr(body, field)
        if value is not None:
            asr[field] = value
            touched.append(f"asr.{field}")
    if body.deepseek is not None:
        section = asr.setdefault("deepseek", {})
        if body.deepseek.base_url is not None:
            section["base_url"] = body.deepseek.base_url.strip()
            touched.append("asr.deepseek.base_url")
        if body.deepseek.timeout is not None:
            section["timeout"] = body.deepseek.timeout
            touched.append("asr.deepseek.timeout")
        key_touched: list[str] = []
        _apply_key(section, "api_key", body.deepseek.api_key, key_touched)
        touched += [f"asr.deepseek.{k}" for k in key_touched]
    if body.openai is not None:
        section = asr.setdefault("openai", {})
        if body.openai.base_url is not None:
            section["base_url"] = body.openai.base_url.strip()
            touched.append("asr.openai.base_url")
        if body.openai.model is not None:
            section["model"] = body.openai.model.strip()
            touched.append("asr.openai.model")
        if body.openai.timeout is not None:
            section["timeout"] = body.openai.timeout
            touched.append("asr.openai.timeout")
        key_touched = []
        _apply_key(section, "api_key", body.openai.api_key, key_touched)
        touched += [f"asr.openai.{k}" for k in key_touched]
    return touched


def _apply_quota(body: QuotaIn) -> list[str]:
    quota = settings.raw.setdefault("quota", {})
    touched: list[str] = []
    for field in QUOTA_FIELDS:
        if field not in body.model_fields_set:
            continue
        value = getattr(body, field)
        if value is None:
            quota[field] = None
            touched.append(f"quota.{field}")
            continue
        if not math.isfinite(value) or value < 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"quota.{field} 必须为空（不限制）或非负有限数",
            )
        quota[field] = None if value == 0 else value
        touched.append(f"quota.{field}")
    return touched


def _apply_agent(body: AgentIn) -> list[str]:
    agent = settings.raw.setdefault("agent", {})
    touched: list[str] = []
    for field, value in body.model_dump(exclude_none=True).items():
        if field == "force_first_round_search":
            agent[field] = bool(value)
            touched.append(field)
            continue
        lo, hi = AGENT_PARAM_RANGES[field]
        if not lo <= value <= hi:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{field} 超出合法区间 [{lo}, {hi}]",
            )
        agent[field] = value
        touched.append(field)
    return touched


@router.put("/config")
def update_config(body: ConfigIn, db: DbSession, user: User = Depends(require_roles("superadmin"))) -> dict:
    # 逐字段 apply 会直接改热生效的 settings.raw；任一后续校验/落盘失败必须整体回滚，
    # 否则运行态与磁盘不一致（请求已 400，但前面字段已生效）。
    snapshot = deepcopy(settings.raw)
    touched: list[str] = []
    try:
        if body.providers is not None:
            touched += _apply_providers(body.providers)
        if body.search is not None:
            touched += _apply_search(body.search)
        if body.asr is not None:
            touched += _apply_asr(body.asr)
        if body.quota is not None:
            touched += _apply_quota(body.quota)
        if body.agent is not None:
            touched += _apply_agent(body.agent)
        if not touched:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有需要保存的变更")
        save_raw(settings.raw)
    except BaseException:
        settings.raw.clear()
        settings.raw.update(snapshot)
        raise
    db.add(AuditLog(
        tenant_id=user.tenant_id, user_id=user.id, action="superadmin_config_update",
        # 只记键名不记值：审计可追溯改了什么，但不把密钥/参数值写进日志
        detail={"keys": touched},
    ))
    db.commit()
    return {"ok": True, "updated": touched}


@router.put("/password")
def update_password(body: PasswordIn, db: DbSession, user: User = Depends(require_roles("superadmin"))) -> dict:
    """修改 superadmin 固定密码：同步 DB 哈希与 config 明文，并写审计。"""
    ensure_password_strength(body.new_password, SUPERADMIN_USERNAME)
    snapshot = deepcopy(settings.raw)
    user.password_hash = hash_password(body.new_password)
    section = settings.raw.setdefault("superadmin", {})
    section["password"] = body.new_password
    section["password_source"] = "config"
    try:
        save_raw(settings.raw)
    except BaseException:
        settings.raw.clear()
        settings.raw.update(snapshot)
        raise
    db.add(AuditLog(
        tenant_id=user.tenant_id, user_id=user.id,
        action="superadmin_password_set", detail={},
    ))
    db.commit()
    warning = None
    if os.environ.get(SUPERADMIN_ENV_VAR):
        warning = "环境变量 NEV_SUPERADMIN_PASSWORD 已设置，下次启动会覆盖本次修改"
    return {"ok": True, "password_source": "config", "warning": warning}


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


@router.post("/config/test")
async def test_slot(body: TestIn, user: User = Depends(require_roles("superadmin"))) -> dict:
    """按当前已保存配置实测一个槽位的连通性（配置完先保存再测试）。"""
    started = time.perf_counter()

    if body.slot in ("main", "aux", "background"):
        provider = get_main_provider() if body.slot == "main" else get_aux_provider()
        slot = "main" if body.slot == "main" else "aux"
        if not provider.api_key:
            return {"ok": False, "slot": slot, "error": "该槽位未配置 api_key", "latency_ms": 0}
        try:
            result = await provider.chat(
                [{"role": "user", "content": "连通性测试：请只回复两个字「正常」"}],
                max_tokens=16,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001  测试接口把一切失败转为可读结果
            return {"ok": False, "slot": slot, "error": str(exc), "latency_ms": _elapsed_ms(started)}
        return {
            "ok": True, "slot": slot, "model": provider.model,
            "reply": result.content[:100], "latency_ms": _elapsed_ms(started),
        }

    if body.slot == "embedding":
        from backend.rag.embedder import Embedder

        embedder = Embedder()
        try:
            vectors = embedder.embed(["连通性测试"])
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "slot": body.slot, "error": str(exc), "latency_ms": _elapsed_ms(started)}
        return {
            "ok": True, "slot": body.slot, "model": embedder.model,
            "detail": f"返回 {len(vectors)} 条 × {len(vectors[0]) if vectors else 0} 维",
            "latency_ms": _elapsed_ms(started),
        }

    if body.slot == "rerank":
        lm = settings.local_models
        url = str(lm.get("rerank_url") or "").strip()
        if not url:
            return {"ok": False, "slot": body.slot, "error": "rerank_url 未配置", "latency_ms": 0}
        model = str(lm.get("rerank_model") or "")
        api_key = str(lm.get("rerank_key") or lm.get("embedding_key") or "")
        try:
            ranked = rerank_api(
                url, api_key, model, "动力电池故障",
                ["低温环境下锂电池续航衰减明显", "直流快充桩的充电流程与握手协议"],
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "slot": body.slot, "error": str(exc), "latency_ms": _elapsed_ms(started)}
        return {
            "ok": True, "slot": body.slot, "model": model,
            "detail": f"top1=文档{ranked[0][0] + 1}（score {ranked[0][1]:.3f}）",
            "latency_ms": _elapsed_ms(started),
        }

    from backend.core.providers.search import SearchUnavailable, primary_name, search_with_fallback

    try:
        hits = await search_with_fallback("新能源汽车 动力电池 故障", count=3)
    except SearchUnavailable as exc:
        return {"ok": False, "slot": "search", "error": str(exc), "latency_ms": _elapsed_ms(started)}
    return {
        "ok": True, "slot": "search",
        "provider": hits[0].provider if hits else primary_name(),
        "detail": f"返回 {len(hits)} 条结果",
        "titles": [h.title[:60] for h in hits[:3]],
        "latency_ms": _elapsed_ms(started),
    }


@router.post("/test/search")
async def test_search(body: SearchTestIn, user: User = Depends(require_roles("superadmin"))) -> dict:
    """搜索连通性测试：指定 provider 直连；不指定则走当前主备策略。"""
    from backend.core.providers.search import (
        SearchUnavailable,
        is_available,
        primary_name,
        search_direct,
        search_with_fallback,
    )

    started = time.perf_counter()
    name = body.provider or primary_name()
    if not is_available(name):
        return {"ok": False, "provider": name, "error": "该 provider 未配置", "latency_ms": 0}
    try:
        if body.provider:
            hits = await search_direct(body.provider, body.query, count=3)
        else:
            hits = await search_with_fallback(body.query, count=3)
    except SearchUnavailable as exc:
        return {"ok": False, "provider": name, "error": str(exc), "latency_ms": _elapsed_ms(started)}
    return {
        "ok": True,
        "provider": hits[0].provider if hits else name,
        "count": len(hits),
        "titles": [h.title[:60] for h in hits[:3]],
        "latency_ms": _elapsed_ms(started),
    }
