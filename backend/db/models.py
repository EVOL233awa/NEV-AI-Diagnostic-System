"""ORM 模型：全部业务表从第一天带 tenant_id。

embeddings（sqlite-vec 虚拟表）与 kb_chunks_fts（FTS5 虚拟表）由
向量库/全文索引模块以原生 SQL 创建，不在 ORM 内。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


def _now() -> datetime:
    return datetime.now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    # 账号登录（user001/staff001/admin）；phone 为手机号登录时期的遗留列，仅存历史数据
    username: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))  # owner / staff / admin
    display_name: Mapped[str] = mapped_column(String(64), default="")
    # 店员可见我的对话记录，默认开启
    privacy_share_dialog: Mapped[bool] = mapped_column(Boolean, default=True)
    # 管理员可查看我的对话原文（质量复核用），默认关闭；阶段/摘要/证据链不受此开关影响
    privacy_share_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    vehicles: Mapped[list["OwnerVehicle"]] = relationship(back_populates="owner")


class VehicleProfile(Base):
    """车辆档案（跨会话按车归档）。"""

    __tablename__ = "vehicle_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    vin: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    plate_no: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    brand: Mapped[str] = mapped_column(String(64), default="")
    model_name: Mapped[str] = mapped_column(String(64), default="")
    model_year: Mapped[str] = mapped_column(String(16), default="")
    power_type: Mapped[str] = mapped_column(String(16), default="")  # EV / PHEV / ...
    notes: Mapped[str] = mapped_column(Text, default="")
    # 里程（km，可选）：0–2,000,000，接口层校验
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class OwnerVehicle(Base):
    """车主 ↔ 车辆绑定（谁名下有哪些车）。"""

    __tablename__ = "owner_vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle_profiles.id"), index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    owner: Mapped[User] = relationship(back_populates="vehicles")
    vehicle: Mapped[VehicleProfile] = relationship()


class Session(Base):
    """诊断会话。channel 区分车主端对话与店内诊断台。"""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_profiles.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="owner")  # owner / staff
    title: Mapped[str] = mapped_column(String(128), default="新诊断会话")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / closed
    # ask_user 待回答调用随会话落库，支持离线续答
    pending_questions: Mapped[list | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    # 诊断状态卡：update_case_notes 工具维护，每轮临时注入
    case_notes: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    # 上下文压缩（双阀门）：前情摘要与已压缩消息边界（messages 原文保留）
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summarized_until_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    messages: Mapped[list["Message"]] = relationship(back_populates="session")


class Message(Base):
    """对话消息。role: user / assistant / tool / system。

    is_temp 对应 AstrBot mark_as_temp 式注入：状态卡等临时块
    单轮拼装、不进对话历史，只随请求发送时以临时消息形式存在。
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Agentic 循环产物：诊断 JSON（严重度/故障假设/引用）与通俗摘要
    diag_json: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    is_temp: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped[Session] = relationship(back_populates="messages")


class RetrievalTrace(Base):
    """检索证据链：一条命中 = 一行，按 evidence_key（E1/E2…）与诊断假设关联。

    只用于管理员质控与统计；不进入模型上下文（工具结果文本除外），
    不返回车主/店员接口。message_id 在最终 assistant 消息落库后回填；
    会话级证据编号单调递增，跨工具调用与 ask_user 续答不冲突。
    """

    __tablename__ = "retrieval_traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True, index=True)
    evidence_key: Mapped[str] = mapped_column(String(16), default="")  # E1、E2…
    kind: Mapped[str] = mapped_column(String(8), default="kb")  # kb / web
    query: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
    rank: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(256), default="")
    url: Mapped[str] = mapped_column(String(1024), default="")
    doc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_path: Mapped[str] = mapped_column(String(256), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    snippet: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class KbDocument(Base):
    """知识库文档（来源可溯源：source_url / source_note）。"""

    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    title: Mapped[str] = mapped_column(String(256))
    filename: Mapped[str] = mapped_column(String(256), default="")
    category: Mapped[str] = mapped_column(String(32), default="general")  # dtc / 三电 / general / case
    source_url: Mapped[str] = mapped_column(String(512), default="")
    source_note: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(16), default="ready")  # parsing / ready / failed
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class KbChunk(Base):
    """知识块：结构感知分块的最小检索单元，带来源定位。"""

    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("kb_documents.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    section_path: Mapped[str] = mapped_column(String(256), default="")  # 章节路径，如 "3.2 充电系统"
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Case(Base):
    """门店沉淀案例（数据飞轮回流知识库检索范围）。"""

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_profiles.id"), nullable=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(256))
    symptoms: Mapped[str] = mapped_column(Text, default="")
    diagnosis: Mapped[str] = mapped_column(Text, default="")
    repair_result: Mapped[str] = mapped_column(Text, default="")
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Appointment(Base):
    """预约单：商业闭环衔接点。summary_card 是诊断摘要卡 JSON，
    不受车主隐私开关影响、始终对店员可见。"""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_profiles.id"), nullable=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    summary_card: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    appointment_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/accepted/completed/cancelled
    shop_note: Mapped[str] = mapped_column(Text, default="")
    repair_result: Mapped[str] = mapped_column(Text, default="")
    accepted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class ProviderConfig(Base):
    """六类槽位的非密钥配置（密钥只在 data/config.json）。"""

    __tablename__ = "provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    slot: Mapped[str] = mapped_column(String(32), index=True)  # main/embedding/rerank/search/asr
    provider_type: Mapped[str] = mapped_column(String(32), default="")  # deepseek / tavily / llama-server / ...
    base_url: Mapped[str] = mapped_column(String(256), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    params: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class UsageStat(Base):
    """每次模型调用的 token/成本流水（AstrBot provider_stats 同款蓝本）。"""

    __tablename__ = "usage_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    slot: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    # 统一 USD（估算）；主模型 token 成本无法可靠估算时为 None，仅搜索/ASR 有值
    cost_estimate: Mapped[float | None] = mapped_column(Float, default=None, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)  # ASR 音频时长（毫秒）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class AuditLog(Base):
    """审计日志：谁在什么时间做了什么关键操作。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
