"""superadmin 调试后台（2026-09-29 用户裁定）：供应商与 Agent 运行参数在线配置。

定位类似 AstrBot WebUI 的供应商配置页，仅供部署者本人调试使用：
- 读写 data/config.json（密钥唯一宿主）：改完即落盘，运行中进程热生效
  （provider/embedder/压缩/循环参数均为每次调用实时读取；server/security 除外）。
- 密钥单向模糊：GET 只回掩码，PUT 留空/缺省 = 保持原值——token 泄露也不会拖出真 key。
- 全部接口 require_roles("superadmin")；admin 不可见（admin_users 已隔离）。
"""
from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.deps import DbSession, require_roles
from backend.config import (
    AGENT_DEFAULTS,
    AGENT_PARAM_RANGES,
    APP_VERSION,
    save_raw,
    settings,
)
from backend.core.providers.llm import get_background_provider, get_main_provider
from backend.db.models import AuditLog, User

router = APIRouter(prefix="/api/superadmin", tags=["superadmin"])

# PUT 里 api_key 传空串视同「不修改」：真要吊销 key 请直接改服务器上的 config.json
EMPTY_KEY = ""


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


class ProvidersIn(BaseModel):
    main: ProviderUpsert | None = None
    background: ProviderUpsert | None = None
    embedding: ProviderUpsert | None = None
    web_search: ProviderUpsert | None = None
    subagent_url: str | None = Field(default=None, max_length=256)
    rerank_url: str | None = Field(default=None, max_length=256)


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


class ConfigIn(BaseModel):
    providers: ProvidersIn | None = None
    agent: AgentIn | None = None


class TestIn(BaseModel):
    slot: Literal["main", "background", "embedding", "web_search"]


def _provider_view() -> dict[str, Any]:
    ds = settings.deepseek
    lm = settings.local_models
    tavily_key = str(settings.tavily.get("api_key") or "")
    return {
        "main": {
            "base_url": str(ds.get("base_url", "")),
            "model": str(ds.get("main_model", "")),
            "has_key": bool(ds.get("main_key")),
            "key_masked": _mask(str(ds.get("main_key") or "")),
        },
        "background": {
            "base_url": str(ds.get("background_base_url", "")),
            "model": str(ds.get("background_model", "")),
            "has_key": bool(ds.get("background_key") or ds.get("main_key")),
            "key_masked": _mask(str(ds.get("background_key") or ds.get("main_key") or "")),
        },
        "embedding": {
            "base_url": str(lm.get("embedding_url", "")),
            "model": str(lm.get("embedding_model", "")),
            "has_key": bool(lm.get("embedding_key")),
            "key_masked": _mask(str(lm.get("embedding_key") or "")),
        },
        "web_search": {
            "has_key": bool(tavily_key),
            "key_masked": _mask(tavily_key),
        },
        "subagent_url": str(lm.get("subagent_url", "")),
        "rerank_url": str(lm.get("rerank_url", "")),
    }


def _agent_view() -> dict[str, Any]:
    configured = settings.agent
    return {key: configured.get(key, default) for key, default in AGENT_DEFAULTS.items()}


@router.get("/config")
def get_config(user: User = Depends(require_roles("superadmin"))) -> dict:
    return {
        "providers": _provider_view(),
        "agent": _agent_view(),
        "server": {
            "host": settings.host,
            "port": settings.port,
            "version": APP_VERSION,
            # 这些键改了要重启进程才生效（其余全部热生效）
            "restart_required_keys": ["server.host", "server.port", "cors_origins", "security.jwt_secret"],
        },
    }


def _apply_provider(section: dict[str, Any], upsert: ProviderUpsert, key_field: str,
                    url_field: str = "base_url", model_field: str | None = None) -> list[str]:
    touched: list[str] = []
    if upsert.base_url is not None:
        section[url_field] = upsert.base_url.strip()
        touched.append(url_field)
    if upsert.model is not None and model_field:
        section[model_field] = upsert.model.strip()
        touched.append(model_field)
    if upsert.api_key:  # None/空串 = 保持原值
        section[key_field] = upsert.api_key.strip()
        touched.append(key_field)
    return touched


def _apply_providers(body: ProvidersIn) -> list[str]:
    raw = settings.raw
    ds = raw.setdefault("deepseek", {})
    lm = raw.setdefault("local_models", {})
    touched: list[str] = []
    if body.main is not None:
        touched += _apply_provider(ds, body.main, "main_key", model_field="main_model")
    if body.background is not None:
        touched += _apply_provider(ds, body.background, "background_key",
                                   url_field="background_base_url", model_field="background_model")
    if body.embedding is not None:
        touched += ["embedding." + t for t in _apply_provider(lm, body.embedding, "embedding_key",
                                                              model_field="embedding_model")]
    if body.web_search is not None and body.web_search.api_key:
        raw.setdefault("tavily", {})["api_key"] = body.web_search.api_key.strip()
        touched.append("tavily.api_key")
    if body.subagent_url is not None:
        lm["subagent_url"] = body.subagent_url.strip()
        touched.append("local_models.subagent_url")
    if body.rerank_url is not None:
        lm["rerank_url"] = body.rerank_url.strip()
        touched.append("local_models.rerank_url")
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
    touched: list[str] = []
    if body.providers is not None:
        touched += _apply_providers(body.providers)
    if body.agent is not None:
        touched += _apply_agent(body.agent)
    if not touched:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有需要保存的变更")
    save_raw(settings.raw)
    db.add(AuditLog(
        tenant_id=user.tenant_id, user_id=user.id, action="superadmin_config_update",
        # 只记键名不记值：审计可追溯改了什么，但不把密钥/参数值写进日志
        detail={"keys": touched},
    ))
    db.commit()
    return {"ok": True, "updated": touched}


@router.post("/config/test")
async def test_slot(body: TestIn, user: User = Depends(require_roles("superadmin"))) -> dict:
    """按当前已保存配置实测一个槽位的连通性（配置完先保存再测试）。"""
    started = time.perf_counter()

    def _elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    if body.slot in ("main", "background"):
        provider = get_main_provider() if body.slot == "main" else get_background_provider()
        if not provider.api_key:
            return {"ok": False, "slot": body.slot, "error": "该槽位未配置 api_key", "latency_ms": 0}
        try:
            result = await provider.chat(
                [{"role": "user", "content": "连通性测试：请只回复两个字「正常」"}],
                max_tokens=16,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001  测试接口把一切失败转为可读结果
            return {"ok": False, "slot": body.slot, "error": str(exc), "latency_ms": _elapsed()}
        return {
            "ok": True, "slot": body.slot, "model": provider.model,
            "reply": result.content[:100], "latency_ms": _elapsed(),
        }

    if body.slot == "embedding":
        from backend.rag.embedder import Embedder

        embedder = Embedder()
        try:
            vectors = embedder.embed(["连通性测试"])
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "slot": body.slot, "error": str(exc), "latency_ms": _elapsed()}
        return {
            "ok": True, "slot": body.slot, "model": embedder.model,
            "detail": f"返回 {len(vectors)} 条 × {len(vectors[0]) if vectors else 0} 维",
            "latency_ms": _elapsed(),
        }

    from backend.core.providers import tavily
    from backend.core.providers.tavily import WebSearchUnavailable

    if not tavily.is_configured():
        return {"ok": False, "slot": body.slot, "error": "Tavily api_key 未配置", "latency_ms": 0}
    try:
        data = await tavily.search("ping", max_results=1)
    except WebSearchUnavailable as exc:
        return {"ok": False, "slot": body.slot, "error": str(exc), "latency_ms": _elapsed()}
    return {
        "ok": True, "slot": body.slot,
        "detail": f"返回 {len(data['results'])} 条结果", "latency_ms": _elapsed(),
    }
