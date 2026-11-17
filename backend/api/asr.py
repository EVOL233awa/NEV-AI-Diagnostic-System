"""语音转文字接口：浏览器录音 → 服务端转写 → 文本回填输入框。

- 角色：owner / staff / admin；superadmin 不提供。
- 不落盘、不记录识别文本；usage_stats 记 provider/时长/成本，审计只记元数据。
- 限额默认不启用（quota 三项 null）；配置正数后超限返回可读提示。
"""
from __future__ import annotations

import struct
import time
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from backend.api.deps import DbSession, require_roles
from backend.config import settings
from backend.core import quota
from backend.core.providers.asr import ASRUnavailable, get_provider
from backend.db.models import AuditLog, User

router = APIRouter(prefix="/api/asr", tags=["asr"])

# provider 错误码 → HTTP 状态（429/503/504 透传上游语义）
_STATUS_BY_CODE: dict[str, int] = {
    "unsupported_format": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "bad_format": status.HTTP_400_BAD_REQUEST,
    "too_large": status.HTTP_413_CONTENT_TOO_LARGE,
    "rate_limit": status.HTTP_429_TOO_MANY_REQUESTS,
    "busy": status.HTTP_503_SERVICE_UNAVAILABLE,
    "timeout": status.HTTP_504_GATEWAY_TIMEOUT,
    "not_configured": status.HTTP_503_SERVICE_UNAVAILABLE,
    "auth": status.HTTP_503_SERVICE_UNAVAILABLE,
    "network": status.HTTP_503_SERVICE_UNAVAILABLE,
    "server": status.HTTP_503_SERVICE_UNAVAILABLE,
    "protocol": status.HTTP_502_BAD_GATEWAY,
    "bad_request": status.HTTP_400_BAD_REQUEST,
    "bad_config": status.HTTP_503_SERVICE_UNAVAILABLE,
}

# 浏览器录音与主流 ASR 上游可接受的容器；仅做 magic bytes 粗判，具体解码交给 provider
_AUDIO_MAGIC: tuple[tuple[str, bytes], ...] = (
    ("wav", b"RIFF"),
    ("ogg", b"OggS"),
    ("webm", b"\x1aE\xdf\xa3"),
    ("mp3", b"ID3"),
)


def _audio_kind(audio: bytes) -> str | None:
    if len(audio) < 12:
        return None
    if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return "wav"
    if audio[4:8] == b"ftyp":
        return "mp4"
    for kind, magic in _AUDIO_MAGIC:
        if audio.startswith(magic):
            return kind
    # MP3 帧同步（无 ID3 标签）；11 位全 1 的帧头
    if audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0:
        return "mp3"
    return None


def _wav_duration_ms(audio: bytes) -> int | None:
    """解析 PCM WAV 的 data 字节数与 byte_rate，服务端独立计算时长。

    客户端上报的 duration_ms 不可信；OpenAI 兼容 provider 又固定返回 0，
    因此以服务端解析值为准（WAV 是浏览器录音的默认格式）。
    """
    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return None
    pos = 12
    byte_rate = 0
    data_size: int | None = None
    while pos + 8 <= len(audio):
        chunk_id = audio[pos:pos + 4]
        size = int.from_bytes(audio[pos + 4:pos + 8], "little")
        body = pos + 8
        if chunk_id == b"fmt " and size >= 16 and body + 16 <= len(audio):
            byte_rate = int.from_bytes(audio[body + 8:body + 12], "little")
        elif chunk_id == b"data":
            available = max(0, len(audio) - body)
            data_size = min(size, available) if size else available
            break
        pos = body + size + (size & 1)
    if byte_rate <= 0 or data_size is None:
        return None
    return int(round(data_size * 1000 / byte_rate))


@router.post("/transcribe")
async def transcribe(
    db: DbSession,
    user: Annotated[User, Depends(require_roles("owner", "staff", "admin"))],
    file: Annotated[UploadFile, File(description="录音文件（WAV/Ogg/webm/mp4 等，取决于 provider）")],
    duration_ms: Annotated[int | None, Form(description="前端上报的录音时长（毫秒）")] = None,
) -> dict:
    asr_cfg = settings.asr
    max_bytes = int(asr_cfg.get("max_bytes") or 8388608)
    max_seconds = int(asr_cfg.get("max_seconds") or 120)

    if duration_ms is not None and (duration_ms <= 0 or duration_ms > max_seconds * 1000):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"录音时长超过限制（最长 {max_seconds} 秒）",
        )

    # 最多读 max_bytes + 1：超限直接 413，不把整文件读进内存
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"音频超过 {max_bytes // 1048576} MiB 限制",
        )
    audio = await file.read(max_bytes + 1)
    if not audio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "音频为空")
    if len(audio) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"音频超过 {max_bytes // 1048576} MiB 限制",
        )
    if _audio_kind(audio) is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "不支持的音频格式（支持 WAV/Ogg/WebM/MP4/MP3）",
        )

    provider = get_provider()
    if not provider.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "语音识别未配置")

    blocked = quota.check_asr(db, user.id)
    if blocked is not None:
        # 限额拒绝也要留痕：便于管理员识别撞额度的账号，不记录识别文本
        db.add(AuditLog(
            tenant_id=user.tenant_id, user_id=user.id, action="asr_transcribe",
            detail={"provider": provider.name, "duration_ms": 0, "ok": False, "blocked": blocked},
        ))
        db.commit()
        if blocked == "user":
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "今日语音识别额度已用完")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "今日语音/搜索预算已用完")

    started = time.perf_counter()
    try:
        result = await provider.transcribe(
            audio,
            file.filename or "audio.wav",
            file.content_type or "application/octet-stream",
        )
    except ASRUnavailable as exc:
        db.add(AuditLog(
            tenant_id=user.tenant_id, user_id=user.id, action="asr_transcribe",
            detail={"provider": provider.name, "duration_ms": int(duration_ms or 0), "ok": False},
        ))
        db.commit()
        raise HTTPException(_STATUS_BY_CODE.get(exc.code, status.HTTP_503_SERVICE_UNAVAILABLE), str(exc)) from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    client_ms = max(int(duration_ms or 0), 0)
    provider_ms = max(int(result.duration_ms or 0), 0)
    wav_ms = _wav_duration_ms(audio) or 0
    # 三者取最大：服务端 WAV 解析能兜住 provider 返回 0、客户端少报两种情况
    final_duration = max(provider_ms, client_ms, wav_ms)
    if final_duration <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "无法确定录音时长；请上传 WAV 录音或提供 duration_ms",
        )
    if final_duration > max_seconds * 1000:
        quota.record_asr(
            db,
            tenant_id=user.tenant_id,
            user_id=user.id,
            provider=result.provider,
            model="",
            duration_ms=final_duration,
            latency_ms=latency_ms,
        )
        db.add(AuditLog(
            tenant_id=user.tenant_id, user_id=user.id, action="asr_transcribe",
            detail={"provider": result.provider, "duration_ms": final_duration,
                    "ok": False, "reason": "duration_over_limit"},
        ))
        db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"录音时长超过限制（最长 {max_seconds} 秒）",
        )
    db.add(AuditLog(
        tenant_id=user.tenant_id, user_id=user.id, action="asr_transcribe",
        detail={"provider": result.provider, "duration_ms": final_duration, "ok": True},
    ))
    quota.record_asr(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        provider=result.provider,
        model="",
        duration_ms=final_duration,
        latency_ms=latency_ms,
    )
    return {
        "text": result.text,
        "duration_ms": final_duration,
        "provider": result.provider,
        "request_id": result.request_id,
    }
