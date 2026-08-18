"""
示例插件：带生命周期钩子的数据源扩展

@Author: 花海
@Date: 2026/08/18 15:00
@Description: 演示统一扩展注册器（ExtensionRegistry）下数据源插件的接入方式：
              1) 生命周期扩展（本示例重点）：ExtensionPoint（build/startup/shutdown）承载数据源生命周期
                 —— build 读取配置段 app.extensions.demo_datasource 构造数据源实例（未连接），
                 startup 应用启动时建立连接，shutdown 应用停机时释放连接（先于框架组件 close）；
              2) 数据源接入（可选配套）：DemoDatasource 实现 DatabaseFactoryInterface（SPI，见 SPI-Extensions.md §4.2），
                 调用 register_demo_datasource_factory() 注册进 DatabaseRegistry 后，app.db.type=demo
                 即被 create_app 装配为 db 组件（会话/健康检查/优雅停机）。
              启用方式：application.yml 声明 app.extensions.enabled: [demo_datasource]。
              注册时机：扩展点模块导入即注册（幂等，无副作用）；数据源类型为演示用途，
              显式调用 register_demo_datasource_factory() 才注册（避免污染全局领域注册表内置条目）。
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from web_infra import DatabaseRegistry, ExtensionPoint, ExtensionRegistry
from web_infra.db.sqlite_session import SqliteSession

#: 示例扩展点名（与 app.extensions.enabled 匹配）
DEMO_DATASOURCE_EXTENSION = "demo_datasource"


class DemoDatasource:
    """演示数据源（DatabaseFactoryInterface 实现，基于 SQLite，带显式连接生命周期）"""

    def __init__(self, db_path: str = ":memory:") -> None:
        """构造数据源（仅保存配置，不建立连接；连接由 startup 钩子建立）。

        :param db_path: SQLite 数据文件路径（默认内存库）
        """
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self.started = False

    @property
    def connected(self) -> bool:
        """是否已建立连接（startup 钩子执行后为 True）"""
        return self._conn is not None

    # ------------------------------------------------------------------
    # 生命周期（由扩展点钩子调用）
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """建立连接（startup 钩子调用）：打开 SQLite 连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self.started = True

    async def disconnect(self) -> None:
        """释放连接（shutdown 钩子调用）"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self.started = False

    # ------------------------------------------------------------------
    # DatabaseFactoryInterface（SPI 契约）
    # ------------------------------------------------------------------

    def create_session(self) -> SqliteSession:
        """创建会话；未连接（startup 钩子未执行）时抛 RuntimeError 快速失败"""
        if self._conn is None:
            raise RuntimeError("demo 数据源未连接（startup 钩子未执行）")
        return SqliteSession(self._conn)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[SqliteSession, None]:
        """异步上下文管理器：进入创建会话，退出自动提交（异常回滚），业务无需 try/finally"""
        session = self.create_session()
        with session.transaction():
            yield session

    async def close(self) -> None:
        """关闭数据源（与 disconnect 一致，供 _shutdown 统一调用 close 的兜底）"""
        await self.disconnect()

    async def health_check(self) -> bool:
        """健康检查：连接可用性探测（SELECT 1 失败视为不健康；未连接视为不健康）"""
        if self._conn is None:
            return False
        try:
            with self._conn:
                self._conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False


# ---------------------------------------------------------------------------
# 扩展点钩子（build / startup / shutdown）
# ---------------------------------------------------------------------------


def build_demo_datasource(options: dict[str, Any], ctx: dict[str, Any]) -> DemoDatasource:
    """扩展点装配期构建：读取配置段构造数据源实例（未连接）。

    :param options: 扩展点配置段（app.extensions.demo_datasource，如 db_path）
    :param ctx: 装配上下文（{"settings": Settings, "components": 已装配组件 dict}）
    :return: 未连接的数据源实例
    """
    return DemoDatasource(db_path=options.get("db_path") or ":memory:")


async def startup_demo_datasource(datasource: DemoDatasource) -> None:
    """扩展点启动钩子：应用启动时建立连接（startup 按拓扑序执行）"""
    await datasource.connect()


async def shutdown_demo_datasource(datasource: DemoDatasource) -> None:
    """扩展点停机钩子：应用停机时释放连接（逆序执行，先于框架组件 close）"""
    await datasource.disconnect()


# ---------------------------------------------------------------------------
# 注册（模块导入即注册，幂等）
# ---------------------------------------------------------------------------


def register_demo_datasource_extension() -> None:
    """注册示例数据源扩展点（幂等，同名显式覆盖）：app.extensions.enabled 声明即启用"""
    ExtensionRegistry.register(
        ExtensionPoint(
            name=DEMO_DATASOURCE_EXTENSION,
            description="示例数据源扩展（生命周期钩子：startup 连接 / shutdown 释放）",
            build=build_demo_datasource,
            startup=startup_demo_datasource,
            shutdown=shutdown_demo_datasource,
        ),
        overwrite=True,
    )


def _demo_factory(params: dict[str, Any]) -> DemoDatasource:
    """demo 数据源工厂（DatabaseRegistry 条目）：入参实例连接参数，返回数据源实例"""
    return DemoDatasource(db_path=params.get("path") or ":memory:")


def register_demo_datasource_factory() -> None:
    """注册 demo 数据源类型（幂等）：app.db.type=demo 装配为 db 组件（SPI-Extensions.md §4.2）"""
    DatabaseRegistry.register("demo", _demo_factory)


# 模块导入即注册扩展点（幂等，可重复导入）；数据源类型（DatabaseRegistry）由业务显式调用
# register_demo_datasource_factory() 注册（演示用途，避免污染全局领域注册表内置条目）
register_demo_datasource_extension()
