"""
CDC 同步目标 SPI

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 同步目标契约（搜索引擎数据同步方案 §4.3）：把变更事件写入目标存储（默认 Elasticsearch）。
              upsert 为 INSERT/UPDATE 写入或覆盖（doc_id 幂等），delete 为 DELETE 事件删除目标文档。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from web_infra.capabilities.search.sync.cdc_change_event import CdcChangeEvent


@runtime_checkable
class CdcSyncTargetInterface(Protocol):
    """同步目标契约：把变更事件写入目标存储（默认 Elasticsearch）

    实现方（如 EsCdcSyncTarget）负责将统一事件转化为目标写入动作，
    写入失败抛可重试异常（E3-SRCH-011），由 Pipeline 统一重试/暂停。
    """

    async def upsert(self, event: CdcChangeEvent) -> None:
        """写入或覆盖一条目标文档（INSERT/UPDATE，doc_id 幂等）。

        :param event: 变更事件（含主键与 after 镜像）
        """
        ...

    async def delete(self, event: CdcChangeEvent) -> None:
        """按主键删除目标文档（DELETE）。

        :param event: 变更事件（含主键，after 视实现决定是否用于软删标记）
        """
        ...

    async def start(self) -> None:
        """启动目标：预连接/预建索引（幂等），由 Pipeline 在消费前调用"""
        ...

    async def stop(self) -> None:
        """停止目标：释放资源（应用停机/测试收尾调用）"""
        ...
