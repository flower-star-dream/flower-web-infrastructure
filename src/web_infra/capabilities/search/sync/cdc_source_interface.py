"""
CDC 数据源 SPI

@Author: 花海
@Date: 2026/08/22 15:00
@Description: CDC 数据源契约（搜索引擎数据同步方案 §4.1）：订阅数据库变更并产出统一事件。
              实现方负责连接数据源、解析变更日志、转换为 CdcChangeEvent 并保序推送，
              连接中断自动重连并从已持久化位点续读。
"""
from __future__ import annotations

from typing import Awaitable, Callable, Protocol, runtime_checkable

from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent

#: 变更事件处理器签名：由 CdcSyncPipeline 注入，消费一个 CDC 变更事件
CdcEventHandler = Callable[[CdcChangeEvent], Awaitable[None]]


@runtime_checkable
class CdcSourceInterface(Protocol):
    """CDC 数据源契约：订阅数据库变更并产出统一事件

    实现方（如 MysqlBinlogCdcSource）负责：
    1. 连接数据源并解析其变更日志（binlog / WAL / change stream）；
    2. 将数据库差异事件转换为 CdcChangeEvent（主键/前后镜像/位点）；
    3. 向注册的 handler 顺序推送事件（分区内保序）；
    4. 连接中断自动重连，并从已持久化位点续读。
    """

    def subscribe(self, handler: CdcEventHandler) -> None:
        """注册事件处理器（启动前调用；同一源仅允许一个处理器）。

        :param handler: 变更事件处理器（由 CdcSyncPipeline 注入）
        """
        ...

    async def start(self) -> None:
        """启动监听：建立数据源连接并从已持久化位点开始消费"""
        ...

    async def stop(self) -> None:
        """停止监听：中断连接并释放资源"""
        ...
