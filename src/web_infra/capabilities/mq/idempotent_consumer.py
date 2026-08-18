"""
消息幂等消费封装

@Author: 花海
@Date: 2026/08/14 19:00
@Description: 消息消费幂等封装（规范 §9.2：所有消费者以 bizId + msgId 为幂等键，保留 7 天；
              首次写入幂等键成功后执行业务，重复消费直接跳过视为 ACK；
              业务失败回滚幂等键允许重试，配合手动 ACK / DLQ（§9.1/§9.6））。
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from web_infra.capabilities.mq.message import Message

logger = logging.getLogger("web_infra.capabilities.mq.idempotent_consumer")


class IdempotentConsumer:
    """消息幂等消费封装（先占幂等键再执行业务，规范 §9.2 原子性）"""

    _RETAIN_DAYS = 7  # 幂等键保留 7 天（规范 §9.2，区别于 API 幂等键 24h 重试窗口）

    def __init__(
        self,
        store: Any,
        *,
        retain_days: int = _RETAIN_DAYS,
        biz_id_field: str = "biz_id",
    ) -> None:
        """初始化幂等消费封装。

        :param store: 消息幂等键存储（内存默认 / Redis 跨实例）
        :param retain_days: 幂等键保留天数（默认 7 天，规范 §9.2）
        :param biz_id_field: 业务键字段名（消息体中的业务键，如 orderId）
        """
        self._store = store
        self._retain_seconds = retain_days * 86400
        self._biz_id_field = biz_id_field

    async def consume(self, message: Message, handler: Callable[[Message], Awaitable[None]]) -> bool:
        """消费一条消息：首次执行 handler 并返回 True；重复消费跳过并返回 False。

        :param message: 统一消息（message_id + body.biz_id 组成幂等键）
        :param handler: 业务处理函数（业务成功即视为消费成功，异常由调用方决定重试/DLQ）
        :return: True 表示已执行业务；False 表示重复消费已跳过
        :raises Exception: 业务处理异常（幂等键已回滚，允许重试）
        """
        key = self._build_key(message)
        if not await self._store.try_consume(key, self._retain_seconds):
            logger.info(
                "message_duplicate_skipped message_id=%s biz_id=%s", message.message_id, self._biz_id(message)
            )
            return False
        try:
            await handler(message)
        except Exception:
            await self._store.release(key)  # 业务失败：回滚幂等键，允许重试（规范 §9.6）
            raise
        return True

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _biz_id(self, message: Message) -> str:
        """提取业务键（消息体 biz_id，缺失时回退 message_id 保证键不空）"""
        return str(message.body.get(self._biz_id_field) or message.message_id)

    def _build_key(self, message: Message) -> str:
        """幂等键：以业务键（biz_id）为核心，同一业务动作无论 msgId 均去重（规范 §9.2
        覆盖投递重试场景）；无业务键时退化为消息级去重（按 message_id）。"""
        biz = self._biz_id(message)
        if biz != message.message_id:  # 业务键来自消息体
            return f"biz:{biz}"
        return f"msg:{message.message_id}"
