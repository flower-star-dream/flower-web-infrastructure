"""
示例数据源扩展插件测试

@Author: 花海
@Date: 2026/08/18 15:00
@Description: 覆盖示例插件 demo_datasource 的两条接入路径：
              1) 扩展点生命周期（本示例重点）：build 构造数据源实例挂 app.state.extensions，
                 startup 建立连接（可执行 SQL），shutdown 释放连接；
              2) 数据源接入（DatabaseRegistry，显式注册）：app.db.type=demo 装配为 db 组件，
                 会话可用/健康检查正确（未连接不健康、未连接创建会话快速失败）。
              数据源类型为演示用途，测试后清理全局注册，避免污染其他测试的精确断言。
"""
import pytest

from examples.demo_datasource_extension import (
    DEMO_DATASOURCE_EXTENSION,
    DemoDatasource,
    register_demo_datasource_extension,
    register_demo_datasource_factory,
)
from web_infra import create_app
from web_infra.db import DatabaseRegistry


@pytest.fixture(autouse=True)
def _cleanup_demo_factory():
    """测试后清理全局注册的 demo 数据源类型（演示用途显式注册，用完即清）"""
    yield
    DatabaseRegistry.unregister("demo")


def test_extension_registered():
    """示例扩展点已注册（模块导入即注册，幂等）"""
    from web_infra import ExtensionRegistry

    assert DEMO_DATASOURCE_EXTENSION in ExtensionRegistry.names()


def test_demo_factory_registered():
    """显式注册后 demo 数据源类型可装配（app.db.type=demo）"""
    register_demo_datasource_factory()
    assert "demo" in DatabaseRegistry.registered_names()


def test_create_app_extensions_assembly():
    """扩展点装配：build 构造数据源实例并挂 app.state.extensions（未连接）"""
    register_demo_datasource_extension()  # 幂等
    app = create_app({"app.extensions.enabled": [DEMO_DATASOURCE_EXTENSION]})
    datasource = app.state.extensions[DEMO_DATASOURCE_EXTENSION]
    assert isinstance(datasource, DemoDatasource)
    assert not datasource.connected  # build 只构造实例，连接由 startup 钩子建立


@pytest.mark.asyncio
async def test_extension_lifecycle_hooks():
    """生命周期钩子：startup 建立连接（可执行 SQL），shutdown 释放连接"""
    register_demo_datasource_extension()  # 幂等
    app = create_app({"app.extensions.enabled": [DEMO_DATASOURCE_EXTENSION]})
    datasource = app.state.extensions[DEMO_DATASOURCE_EXTENSION]
    async with app.router.lifespan_context(app):  # 进入执行 startup，退出执行 shutdown
        assert datasource.connected and datasource.started
        async with datasource.session() as session:
            session.execute("CREATE TABLE IF NOT EXISTS t_demo (id INTEGER PRIMARY KEY, name TEXT)")
            session.execute("INSERT INTO t_demo (name) VALUES (:name)", {"name": "demo"})
            row = session.query_one("SELECT name FROM t_demo WHERE id = 1")
        assert row == {"name": "demo"}
    assert not datasource.connected  # 停机后连接已释放


def test_database_registry_assembly():
    """数据源接入：app.db.type=demo 装配为 db 组件（未连接，create_session 快速失败）"""
    register_demo_datasource_factory()
    app = create_app({"app.db.type": "demo"})
    db = app.state.components["db"]
    assert isinstance(db, DemoDatasource)
    with pytest.raises(RuntimeError):  # 未连接（startup 钩子未执行）时快速失败
        db.create_session()
