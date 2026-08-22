"""
搜索引擎同步常量

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 搜索引擎数据同步常量（搜索引擎数据同步方案）：位点键、双写 topic、
              outbox 事件类型标记、软删标记字段、批量上限。
"""
from __future__ import annotations


class SearchSyncConstant:
    """搜索引擎同步常量（位点 / 双写 / 软删 / 批量上限）"""

    # 错误码域前缀（随 SearchConstant.ERROR_DOMAIN = "SRCH"）
    ERROR_DOMAIN = "SRCH"

    # Redis 位点 Hash 键（RedisOffsetStore 缺省）
    OFFSET_KEY = "web:search:sync:offsets"

    # 双写同步 Topic（Outbox 消息主题，规范 §5.8 与业务域对齐）
    SYNC_TOPIC = "web-search-sync-topic"

    # Outbox 记录事件类型标记（双写写入器区分同步事件）
    OUTBOX_EVENT_TYPE = "search-sync"

    # 软删标记字段名（EsCdcSyncTarget 默认写入；业务检索统一过滤）
    DELETE_FLAG = "deleted"

    # 批量上限（防 ES 批量过大，Pipeline 攒批上限）
    MAX_BULK_SIZE = 1000
