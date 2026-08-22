"""
双写同步（Outbox 写入器 + 消费组件）

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 双写同步实现（搜索引擎数据同步方案 §6）：复用框架 mq/outbox 可靠投递设施，
              业务事务内写 outbox 记录（与业务数据同库同事务），框架消费后经目标同步 ES。
              写入器承载事务内写入，消费组件复用 IdempotentConsumer 幂等消费并写目标。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.capabilities.mq.message import Message
from web_infra.capabilities.mq.outbox.outbox_record import OutboxRecord
from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent, CdcOp
from web_infra.capabilities.search.sync.cdc_sync_target_interface import CdcSyncTargetInterface
from web_infra.capabilities.search.sync.search_sync_constant import SearchSyncConstant

logger = logging.getLogger("web_infra.capabilities.search.sync.dual_write")


class SearchSyncOutboxWriter:
    """双写同步写入器：业务事务内写入 outbox 记录（与业务数据同库同事务）。

    用法（业务 service 内，session 为 ORM 或通用会话）：
        async with db.orm_session() as session:
            session.add(order)                       # 业务写库
            await writer.record(session, biz_id=str(order.id), table="t_order",
                                op="insert", after=order.to_dict())
    """

    def __init__(self, outbox_store: Any, topic: str = SearchSyncConstant.SYNC_TOPIC) -> None:
        """初始化写入器。

        :param outbox_store: outbox 存储（MysqlOutboxStore 等，append 支持传业务会话同事务）
        :param topic: 双写同步 Topic
        """
        self._store = outbox_store
        self._topic = topic

    async def record(
        self,
        session: Any,
        *,
        biz_id: str,
        table: str,
        op: str,
        before: dict | None = None,
        after: dict | None = None,
        database: str = "",
    ) -> None:
        """同事务写入 outbox 记录（业务数据与同步事件一起提交，保证不丢事件）。

        :param session: 业务会话（与业务写库同一会话；outbox 记录随之提交/回滚）
        :param biz_id: 业务键（幂等键组成部分，如订单 ID）
        :param table: 数据表名
        :param op: 操作类型（insert / update / delete）
        :param before: 变更前镜像（可选，update 时建议传入）
        :param after: 变更后镜像（可选，insert/update 时建议传入）
        :param database: 数据库名（可选，供目标定位）
        :raises ValueError: op 非法
        """
        if op not in {e.value for e in CdcOp}:
            raise ValueError(f"非法操作类型: {op!r}")
        payload = {
            "source": "dual_write",
            "database": database,
            "table": table,
            "op": op,
            "primary_key": {"biz_id": biz_id},
            "before": before or {},
            "after": after or {},
        }
        record = OutboxRecord(topic=self._topic, biz_id=biz_id, payload=payload, tag=op)
        await self._store.append(record, session=session)
        logger.debug("dual_write_recorded table=%s biz_id=%s op=%s", table, biz_id, op)


class SearchSyncOutboxConsumer:
    """双写同步消费组件：复用 IdempotentConsumer 幂等消费 outbox 事件并同步到目标。

    :param idempotent_consumer: 幂等消费封装（复用消息是否已消费判定）
    :param target: 同步目标（EsCdcSyncTarget 等）
    :param delete_strategy: 删除策略（soft 软删 / hard 物理删除）
    :param event_type: outbox 事件类型标记（过滤所属事件）
    """

    def __init__(
        self,
        idempotent_consumer: Any,
        target: CdcSyncTargetInterface,
        *,
        delete_strategy: str = "soft",
        event_type: str = SearchSyncConstant.OUTBOX_EVENT_TYPE,
    ) -> None:
        """初始化消费组件。

        :param idempotent_consumer: IdempotentConsumer 实例
        :param target: 同步目标
        :param delete_strategy: 删除策略
        :param event_type: outbox 事件类型标记
        """
        self._consumer = idempotent_consumer
        self._target = target
        self._delete_strategy = delete_strategy
        self._event_type = event_type

    async def handle(self, message: Message) -> bool:
        """消费一条双写消息（幂等：仅首次执行业务，重复消费跳过）。

        :param message: 统一消息（body 含同步事件 payload）
        :return: True 表示已执行业务；False 表示重复消费已跳过
        """
        return await self._consumer.consume(message, self._apply)

    async def _apply(self, message: Message) -> None:
        """把消息体转为变更事件并写目标（幂等消费的 handler 主体）。

        :raises ValueError: 消息体非法（事件类型/操作类型不匹配）
        """
        payload = message.body
        event_type = payload.get("event_type", self._event_type)
        if event_type != self._event_type:
            logger.warning("dual_write_skip_wrong_event_type event_type=%s", event_type)
            return
        event = self._to_event(payload)
        if event is None:
            return
        if event.op == CdcOp.DELETE:
            await self._target.delete(event)
        else:
            await self._target.upsert(event)
        logger.info("dual_write_applied table=%s op=%s pk=%s", event.table, event.op.value, event.primary_key)

    # ------------------------------------------------------------------
    # 内部：payload → CdcChangeEvent
    # ------------------------------------------------------------------

    def _to_event(self, payload: dict[str, Any]) -> CdcChangeEvent | None:
        """把 outbox payload 解析为统一变更事件（op 非法时记日志返回 None）。

        :raises ValueError: op 非法时抛出（Consumer 异常返回将触发重试）
        """
        op_str = payload.get("op", "")
        op = CdcOp(op_str) if op_str in {e.value for e in CdcOp} else None
        if op is None:
            raise ValueError(f"非法操作类型: {op_str!r}")
        pk = payload.get("primary_key") or {}
        return CdcChangeEvent(
            source=payload.get("source", "dual_write"),
            database=payload.get("database", ""),
            table=payload.get("table", ""),
            op=op,
            primary_key=pk,
            before=payload.get("before"),
            after=payload.get("after"),
            position=payload.get("position"),
        )
