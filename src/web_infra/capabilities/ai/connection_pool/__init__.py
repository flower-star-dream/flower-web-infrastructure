"""
连接池模块

@Author: 花海
@Date: 2026/08/14 22:30
@Description: 导出模型网关连接池管理（AI 规范 §5.1）：连接池配置与流式/非流式分池管理器。
              连接池相关能力独立成包，与 ai 模块其他静态资源/能力隔离。
"""
from web_infra.capabilities.ai.connection_pool.connection_pool_config import ConnectionPoolConfig
from web_infra.capabilities.ai.connection_pool.connection_pool import ConnectionPoolManager

__all__ = [
    "ConnectionPoolConfig",
    "ConnectionPoolManager",
]
