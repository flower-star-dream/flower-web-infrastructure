"""
Outbox 清理任务

@Author: 花海
@Date: 2026/08/14 19:00
@Description: Outbox 已发送记录清理（规范 §21.3：已发送保留 7 天后删除或归档，以 created_at 为判断依据，
              完成后回写 cleaned_at）。清理走独立定时作业且命名含模块归属（如 order:job:message-outbox-cleanup），
              与业务归档作业分离，调度遵守 §23 防重复执行。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("web_infra.mq.outbox")


class OutboxCleaner:
    """Outbox 已发送记录清理器"""

    def __init__(self, store: Any, *, retain_days: int = 7) -> None:
        """初始化清理器。

        :param store: Outbox 存储（OutboxStoreInterface）
        :param retain_days: 已发送记录保留天数（默认 7 天，规范 §21.3）
        """
        self._store = store
        self._retain_days = retain_days

    async def cleanup(self) -> int:
        """清理已发送超过保留期的记录，返回清理条数"""
        before = datetime.now(timezone.utc) - timedelta(days=self._retain_days)
        removed = await self._store.cleanup_sent(before)
        if removed:
            logger.info("outbox_cleanup_removed count=%s retain_days=%s", removed, self._retain_days)
        return removed
