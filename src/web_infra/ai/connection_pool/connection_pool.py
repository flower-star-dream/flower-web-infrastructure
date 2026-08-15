"""
模型网关连接池管理器

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 统一模型网关连接池管理（AI 规范 §5.1）：
              流式/非流式分池（httpx.AsyncClient + Limits），流式池上限须小于非流式池防互相挤占；
              懒加载单例 + asyncio.Lock 防并发重复创建；close 释放全部连接。
              连接池指标（AI-9）：活跃/等待连接数 Gauge（ai_connection_pool_active/waiting，池名低基数），
              在池获取路径与 /metrics 抓取前刷新（update_pool_metrics），池满告警联动熔断/限流由上层接入。
"""
from __future__ import annotations

import asyncio
from typing import Any

from web_infra.ai.connection_pool.connection_pool_config import ConnectionPoolConfig
from web_infra.monitoring.ai_metrics import record_ai_connection_pool_usage


class ConnectionPoolManager:
    """模型网关连接池管理器（流式/非流式分池）"""

    def __init__(self, config: ConnectionPoolConfig | None = None) -> None:
        """初始化连接池管理器。

        :param config: 连接池配置（默认流式 16 / 非流式 64）
        """
        self._config = config or ConnectionPoolConfig()
        self._stream_client: Any = None
        self._sync_client: Any = None
        self._lock = asyncio.Lock()

    async def get_stream_client(self) -> Any:
        """获取流式调用客户端（懒加载单例，连接长时间占用；返回前刷新 AI-9 连接池指标）"""
        if self._stream_client is None:
            async with self._lock:
                if self._stream_client is None:
                    self._stream_client = self._build_client(
                        max_connections=self._config.stream_max_connections,
                        max_keepalive=self._config.stream_max_keepalive_connections,
                        read_timeout=self._config.stream_read_timeout_seconds,
                    )
        self.update_pool_metrics()
        return self._stream_client

    async def get_sync_client(self) -> Any:
        """获取非流式调用客户端（懒加载单例；返回前刷新 AI-9 连接池指标）"""
        if self._sync_client is None:
            async with self._lock:
                if self._sync_client is None:
                    self._sync_client = self._build_client(
                        max_connections=self._config.sync_max_connections,
                        max_keepalive=self._config.sync_max_keepalive_connections,
                        read_timeout=self._config.sync_read_timeout_seconds,
                    )
        self.update_pool_metrics()
        return self._sync_client

    async def close(self) -> None:
        """关闭全部连接池（应用停机时调用，规范 §19.6 优雅停机；关闭后指标置 0，AI-9）"""
        async with self._lock:
            for client in (self._stream_client, self._sync_client):
                if client is not None:
                    await client.aclose()
            self._stream_client = None
            self._sync_client = None
        self.update_pool_metrics()

    def update_pool_metrics(self) -> None:
        """刷新 AI 连接池运行指标（AI-9：活跃/等待连接数，供 /metrics 抓取链路调用）。

        活跃连接 = httpcore 连接池内已建连接数（含处理中与复用中），等待连接 = 尚未分配到连接的排队请求数；
        连接池未建立或读取失败时各指标置 0。依赖 httpx/httpcore 私有结构（_transport._pool），
        读取失败按 0 兜底不抛异常；池满告警联动熔断/限流由上层接入（规范 AI-9）。
        """
        for pool_name, client in (("stream", self._stream_client), ("sync", self._sync_client)):
            active = waiting = 0
            if client is not None:
                try:
                    transport = getattr(client, "_transport", None)
                    pool = getattr(transport, "_pool", None)
                    connections = getattr(pool, "_connections", None) or []
                    # 活跃 = 非空闲连接（已分配处理中；空闲 keepalive 连接不计入活跃）
                    active = sum(
                        1
                        for conn in connections
                        if not (callable((is_idle := getattr(conn, "is_idle", None))) and is_idle())
                    )
                    requests = getattr(pool, "_requests", None) or []
                    # 等待 = 请求队列中尚未分配到连接的排队请求数（httpcore.AsyncPoolRequest.is_queued）
                    waiting = sum(
                        1
                        for req in requests
                        if callable((is_queued := getattr(req, "is_queued", None))) and is_queued()
                    )
                except Exception:
                    # 私有结构随版本变化，读取失败按 0 兜底，监控不阻断业务主链路
                    active = waiting = 0
            record_ai_connection_pool_usage(pool_name, active, waiting)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _build_client(self, max_connections: int, max_keepalive: int, read_timeout: float) -> Any:
        """构造 httpx.AsyncClient（延迟导入 httpx）"""
        import httpx

        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
        )
        timeout = httpx.Timeout(
            connect=self._config.connect_timeout_seconds,
            read=read_timeout,
            write=self._config.connect_timeout_seconds * 2,  # 写超时：请求体较小，放宽
            pool=self._config.connect_timeout_seconds,  # 连接池获取超时
        )
        return httpx.AsyncClient(limits=limits, timeout=timeout)
