"""
MongoDB 通用数据库工厂接口

@Author: 花海
@Date: 2026/08/18 10:00
@Description: MongoDB 数据库工厂接口（SPI 扩展点），遵循规范 §3 与 §10。
              用户扩展其他文档数据库实现时，实现本接口即可接入框架装配（MongoDatabaseRegistry）：
              - create_session：创建通用 MongoDB 会话（集合级契约 MongoSessionInterface）
              - session：异步上下文管理器（推荐用法，自动提交/回滚/关闭，业务无需 try/finally）
              - close：关闭客户端连接/释放底层资源
              - health_check：健康检查
              可选能力（按需实现即可被框架识别，不强制）：
              - register_document_models(models)：注册 Beanie Document 模型并初始化 ODM（业务模型注册入口）
              - transaction()：多文档事务上下文
              - get_database() / get_collection(name)：原生访问入口
              - update_pool_metrics()：连接池运行指标
"""
from __future__ import annotations

from typing import AsyncContextManager, Protocol, runtime_checkable

from web_infra.capabilities.db.mongo_session_interface import MongoSessionInterface


@runtime_checkable
class MongoDatabaseFactoryInterface(Protocol):
    """MongoDB 通用数据库工厂接口（SPI 扩展点）"""

    async def create_session(self) -> MongoSessionInterface:
        """创建通用 MongoDB 会话"""
        ...

    def session(self) -> AsyncContextManager[MongoSessionInterface]:
        """异步上下文管理器：进入创建会话，退出自动提交（异常回滚）并关闭（业务无需 try/finally）"""
        ...

    async def close(self) -> None:
        """关闭客户端连接/释放底层资源"""
        ...

    async def health_check(self) -> bool:
        """健康检查"""
        ...
