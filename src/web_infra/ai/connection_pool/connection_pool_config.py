"""
连接池配置

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 模型网关连接池配置（AI 规范 §5.1：流式/非流式分池，流式池上限须小于非流式池）。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionPoolConfig:
    """连接池配置（流式/非流式分池）"""

    # 流式池：连接长时间占用，上限须小于非流式池（AI 规范 §5.1）
    stream_max_connections: int = 16
    stream_max_keepalive_connections: int = 16
    # 非流式池
    sync_max_connections: int = 64
    sync_max_keepalive_connections: int = 32
    # 超时（连接/读），流式读超时须覆盖生成全量（§4.1）
    connect_timeout_seconds: float = 1.0
    stream_read_timeout_seconds: float = 30.0
    sync_read_timeout_seconds: float = 60.0
