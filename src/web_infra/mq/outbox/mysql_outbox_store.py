"""
MySQL Outbox 存储

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 基于 SQLAlchemy AsyncSession + text() 的 Outbox 本地事务表存储（规范 §21.3/S21-1）。
              append 支持传入业务会话同事务写入（业务数据 + Outbox 消息同库同事务提交，保证不丢消息）；
              next_pending 按 created_at 升序取未发送且退避到期（next_retry_at <= now）的记录；
              字段与 db/init/ddl/001-mq-init-ddl.sql（含 next_retry_at 增量）对齐。
              测试可用 sqlite+aiosqlite 内存库验证 SQL 语义（SQL 为通用 ANSI 子集）。
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from web_infra.mq.outbox.outbox_record import OutboxRecord
from web_infra.mq.outbox.outbox_status import OutboxStatus
from web_infra.mq.outbox.outbox_store_interface import OutboxStoreInterface

# 表名与基础 DDL（db/init/ddl/001-mq-init-ddl.sql + V0.2.0 增量 next_retry_at 列）对齐
_OUTBOX_TABLE = "message_outbox"
_COLUMNS = (
    "msg_id, biz_id, topic, tag, payload, status, retry_count, "
    "created_at, updated_at, cleaned_at, next_retry_at"
)


def _now() -> datetime:
    """当前 UTC 时间（naive，兼容 MySQL DATETIME / SQLite 无时区列）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value: Any) -> datetime | None:
    """解析驱动返回的时间值：MySQL 返回 datetime，SQLite 返回 ISO 字符串"""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class MysqlOutboxStore(OutboxStoreInterface):
    """MySQL Outbox 存储（本地事务表，SQLAlchemy AsyncSession + text()）"""

    def __init__(self, session_factory: Callable[[], AsyncSession] | Any) -> None:
        """初始化存储。

        :param session_factory: 异步会话工厂（`async_sessionmaker[AsyncSession]` 或 `() -> AsyncSession`）；
            append 可额外接收业务会话同事务写入，其余方法内部自建会话并提交
        """
        self._session_factory = session_factory

    @asynccontextmanager
    async def _session_scope(self, session: AsyncSession | None = None) -> AsyncIterator[AsyncSession]:
        """会话作用域：无外部会话时自建并提交/关闭；传入业务会话时不提交（由业务事务统一提交）"""
        own = session is None
        current = session or self._session_factory()
        try:
            yield current
            if own:
                await current.commit()
        except Exception:
            if own:
                await current.rollback()
            raise
        finally:
            if own:
                await current.close()

    async def append(self, record: OutboxRecord, session: AsyncSession | None = None) -> OutboxRecord:
        """追加待发送消息：默认自建会话提交；传入 session 时与业务同事务写入（S21-1）"""
        from sqlalchemy import text

        async with self._session_scope(session) as current:
            if not record.msg_id:
                record.msg_id = uuid.uuid4().hex
            now = _now()
            record.status = OutboxStatus.PENDING
            record.created_at = record.created_at or now
            record.updated_at = record.updated_at or now
            record.next_retry_at = None  # 重新追加视为首次投递，无需退避
            await current.execute(
                text(
                    f"INSERT INTO {_OUTBOX_TABLE} ({_COLUMNS}) VALUES "
                    "(:msg_id, :biz_id, :topic, :tag, :payload, :status, :retry_count, "
                    ":created_at, :updated_at, :cleaned_at, :next_retry_at)"
                ),
                self._bind(record),
            )
            return record

    async def next_pending(self, limit: int = 100) -> list[OutboxRecord]:
        """取待发送消息：未发送且退避到期（next_retry_at 为空或 <= now），按 created_at 升序"""
        from sqlalchemy import text

        async with self._session_scope() as session:
            rows = (
                await session.execute(
                    text(
                        f"SELECT {_COLUMNS} FROM {_OUTBOX_TABLE} "
                        "WHERE status = :status AND (next_retry_at IS NULL OR next_retry_at <= :now) "
                        "ORDER BY created_at ASC LIMIT :limit"
                    ),
                    {"status": int(OutboxStatus.PENDING), "now": _now(), "limit": limit},
                )
            ).mappings().all()
            return [self._from_row(dict(row)) for row in rows]

    async def mark_sent(self, msg_id: str) -> None:
        """投递成功：状态置为已发送"""
        from sqlalchemy import text

        async with self._session_scope() as session:
            await session.execute(
                text(f"UPDATE {_OUTBOX_TABLE} SET status = :status, next_retry_at = NULL, updated_at = :now "
                     "WHERE msg_id = :msg_id"),
                {"status": int(OutboxStatus.SENT), "now": _now(), "msg_id": msg_id},
            )

    async def mark_failed(self, msg_id: str, max_retries: int, retry_delay_seconds: int | None = None) -> None:
        """投递失败：重试次数 +1；未超限设置 next_retry_at 退避时间，超限置失败并清除退避（S9-4）"""
        from sqlalchemy import text

        async with self._session_scope() as session:
            next_retry_at = None if retry_delay_seconds is None else _now() + timedelta(seconds=retry_delay_seconds)
            await session.execute(
                text(
                    f"UPDATE {_OUTBOX_TABLE} SET retry_count = retry_count + 1, updated_at = :now, "
                    "status = CASE WHEN retry_count + 1 >= :max_retries THEN :failed ELSE :pending END, "
                    "next_retry_at = CASE WHEN retry_count + 1 >= :max_retries THEN NULL ELSE :next_retry_at END "
                    "WHERE msg_id = :msg_id"
                ),
                {
                    "now": _now(),
                    "max_retries": max_retries,
                    "failed": int(OutboxStatus.FAILED),
                    "pending": int(OutboxStatus.PENDING),
                    "next_retry_at": next_retry_at,
                    "msg_id": msg_id,
                },
            )

    async def mark_dlq(self, msg_id: str) -> None:
        """投递死信：状态置为死信并清除退避时间（P0-3/S9-7）"""
        from sqlalchemy import text

        async with self._session_scope() as session:
            await session.execute(
                text(f"UPDATE {_OUTBOX_TABLE} SET status = :status, next_retry_at = NULL, updated_at = :now "
                     "WHERE msg_id = :msg_id"),
                {"status": int(OutboxStatus.DLQ), "now": _now(), "msg_id": msg_id},
            )

    async def cleanup_sent(self, before: datetime) -> int:
        """清理已发送且创建时间早于 before 的记录（规范 §21.3），返回清理条数"""
        from sqlalchemy import text

        async with self._session_scope() as session:
            result = await session.execute(
                text(f"DELETE FROM {_OUTBOX_TABLE} WHERE status = :status AND created_at < :before"),
                {"status": int(OutboxStatus.SENT), "before": before},
            )
            return int(getattr(result, "rowcount", 0) or 0)

    # ------------------------------------------------------------------
    # 内部：行/记录互转
    # ------------------------------------------------------------------

    @staticmethod
    def _bind(record: OutboxRecord) -> dict[str, Any]:
        """OutboxRecord -> SQL 绑定参数"""
        return {
            "msg_id": record.msg_id,
            "biz_id": record.biz_id,
            "topic": record.topic,
            "tag": record.tag,
            "payload": json.dumps(record.payload, ensure_ascii=False),
            "status": int(record.status),
            "retry_count": record.retry_count,
            "created_at": record.created_at or _now(),
            "updated_at": record.updated_at or _now(),
            "cleaned_at": record.cleaned_at,
            "next_retry_at": record.next_retry_at,
        }

    @classmethod
    def _from_row(cls, row: dict[str, Any]) -> OutboxRecord:
        """SQL 行 -> OutboxRecord（payload JSON 反序列化，时间为 UTC naive）"""
        return OutboxRecord(
            msg_id=str(row["msg_id"]),
            biz_id=str(row["biz_id"]),
            topic=str(row["topic"]),
            tag=str(row["tag"] or ""),
            payload=json.loads(row["payload"]),
            status=OutboxStatus(int(row["status"])),
            retry_count=int(row["retry_count"]),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
            cleaned_at=_parse_dt(row["cleaned_at"]),
            next_retry_at=_parse_dt(row["next_retry_at"]),
        )
