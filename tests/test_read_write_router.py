"""
读写分离路由与从库会话单元测试（规范 S10-2）

@Author: 花海
@Date: 2026/08/15 09:00
@Description: 验证 ReadWriteRouter 注册/轮询/移除/无从库回退，以及 MySQLConfig / MySQLDatabase
              从库引擎懒加载与会话回退（S10-2 读写分离；在 mock 层用 sqlite 内存引擎替代，
              不连接真实 MySQL）。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine as real_create_async_engine

from web_infra.capabilities.db.mysql_database import MySQLDatabase
from web_infra.capabilities.db.read_write_router import ReadWriteRouter


def _make_fake_create_async_engine(monkeypatch, created_urls):
    """将 MySQLConfig 的 create_async_engine 替换为 sqlite 内存引擎，记录传入的 url（不连真实 MySQL）"""
    import web_infra.capabilities.db.mysql_config as mc

    def _fake_create_async_engine(url, **kwargs):
        # 事件机制与方言无关：用 sqlite 内存引擎替代 MySQL（aiomysql 专属的 connect_args/池参数需剥离）
        kwargs.pop("connect_args", None)
        for pool_arg in ("pool_size", "max_overflow", "pool_timeout", "pool_recycle", "pool_pre_ping", "echo"):
            kwargs.pop(pool_arg, None)
        created_urls.append(str(url))
        return real_create_async_engine("sqlite+aiosqlite:///:memory:", **kwargs)

    monkeypatch.setattr(mc, "create_async_engine", _fake_create_async_engine)


# ------------------------------------------------------------------
# ReadWriteRouter 基础路由
# ------------------------------------------------------------------

def test_router_no_replicas_returns_none():
    """无从库：next_replica 返回 None，read 路由返回 None，write 路由返回主库名"""
    router = ReadWriteRouter(primary_name="primary")
    assert router.next_replica() is None
    assert router.route("read") is None
    assert router.route("write") == "primary"


def test_router_register_and_round_robin():
    """注册多个从库后轮询（round-robin）依次返回并循环"""
    router = ReadWriteRouter(primary_name="primary")
    router.register_replicas(["replica_0", "replica_1", "replica_2"])
    assert router.next_replica() == "replica_0"
    assert router.next_replica() == "replica_1"
    assert router.next_replica() == "replica_2"
    assert router.next_replica() == "replica_0"  # 回到第一个


def test_router_register_replica_idempotent():
    """重复注册同名从库不重复进入轮询"""
    router = ReadWriteRouter()
    router.register_replica("r1")
    router.register_replica("r1")
    assert router.next_replica() == "r1"
    assert router.next_replica() == "r1"


def test_router_remove_replica():
    """移除从库后不再参与轮询；移除全部后返回 None"""
    router = ReadWriteRouter()
    router.register_replicas(["r1", "r2"])
    router.remove_replica("r1")
    assert router.next_replica() == "r2"
    assert router.next_replica() == "r2"
    router.remove_replica("r2")
    assert router.next_replica() is None
    router.remove_replica("not-exist")  # 移除不存在从库静默


def test_router_route_read_uses_replicas():
    """read 路由返回轮询从库名，write 路由返回构造时指定的主库名"""
    router = ReadWriteRouter(primary_name="mysql-primary")
    router.register_replicas(["replica_0", "replica_1"])
    assert router.route("read") == "replica_0"
    assert router.route("read") == "replica_1"
    assert router.route("write") == "mysql-primary"


def test_router_invalid_operation():
    """非法路由操作抛 ValueError"""
    router = ReadWriteRouter()
    with pytest.raises(ValueError):
        router.route("update")


# ------------------------------------------------------------------
# MySQLConfig 从库引擎懒加载（mock 层，不连真实 MySQL）
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mysql_config_replica_names_from_urls(monkeypatch):
    """replica_names 按 replica_urls 数量生成 replica_0..N；未配置时为空"""
    import web_infra.capabilities.db.mysql_config as mc

    created_urls: list[str] = []
    _make_fake_create_async_engine(monkeypatch, created_urls)

    config = mc.MySQLConfig(
        url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app",
        replica_urls=[
            "mysql+aiomysql://root:pwd@127.0.0.1:3307/app",
            "mysql+aiomysql://root:pwd@127.0.0.1:3308/app",
        ],
    )
    assert config.replica_names() == ["replica_0", "replica_1"]
    assert created_urls == []  # 仅声明，未建连

    empty = mc.MySQLConfig(url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app")
    assert empty.replica_names() == []
    await empty.close()


@pytest.mark.asyncio
async def test_mysql_config_replica_session_lazy_creation(monkeypatch):
    """从库引擎懒加载：首次 get_replica_session 才创建，轮询选择从库"""
    import web_infra.capabilities.db.mysql_config as mc

    created_urls: list[str] = []
    _make_fake_create_async_engine(monkeypatch, created_urls)

    config = mc.MySQLConfig(
        url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app",
        replica_urls=["mysql+aiomysql://root:pwd@127.0.0.1:3307/app"],
    )
    assert created_urls == []  # 构造不建连

    session = await config.get_replica_session()  # name 为空：路由轮询到 replica_0
    assert created_urls, "从库引擎应被懒加载创建"
    assert "3307" in created_urls[-1]
    assert len(config._replica_engines) == 1

    # 再次获取复用已创建引擎（不再新建）
    before = len(created_urls)
    await config.get_replica_session(name="replica_0")
    assert len(created_urls) == before

    await session.close()
    await config.close()
    assert config._replica_engines == {}  # close 清空从库引擎


@pytest.mark.asyncio
async def test_mysql_config_get_replica_session_fallback_to_primary(monkeypatch):
    """未配置从库时 get_replica_session 回退主库（仅创建主库引擎）"""
    import web_infra.capabilities.db.mysql_config as mc

    created_urls: list[str] = []
    _make_fake_create_async_engine(monkeypatch, created_urls)

    config = mc.MySQLConfig(url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app")
    session = await config.get_replica_session()
    assert len(created_urls) == 1
    assert "3306" in created_urls[0]
    assert config._replica_engines == {}  # 未创建任何从库引擎

    await session.close()
    await config.close()


@pytest.mark.asyncio
async def test_mysql_config_get_replica_session_unknown_name_fallback(monkeypatch):
    """指定不存在的从库名时回退主库（记 warning，不抛错）"""
    import web_infra.capabilities.db.mysql_config as mc

    created_urls: list[str] = []
    _make_fake_create_async_engine(monkeypatch, created_urls)

    config = mc.MySQLConfig(
        url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app",
        replica_urls=["mysql+aiomysql://root:pwd@127.0.0.1:3307/app"],
    )
    session = await config.get_replica_session(name="replica_99")  # 越界从库名
    assert len(created_urls) == 1
    assert "3306" in created_urls[0]  # 回退主库

    await session.close()
    await config.close()


# ------------------------------------------------------------------
# MySQLDatabase 读写分离会话（mock 层，不连真实 MySQL）
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mysql_database_orm_session_read_replica(monkeypatch):
    """read_replica=True 且配置从库：orm_session 绑定从库会话（懒加载从库引擎）"""
    import web_infra.capabilities.db.mysql_config as mc

    created_urls: list[str] = []
    _make_fake_create_async_engine(monkeypatch, created_urls)

    config = mc.MySQLConfig(
        url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app",
        replica_urls=["mysql+aiomysql://root:pwd@127.0.0.1:3307/app"],
    )
    db = MySQLDatabase(config)
    async with db.orm_session(read_replica=True) as session:
        await session.execute(text("SELECT 1"))
    # 读流量路由从库：仅创建从库引擎（主库引擎未创建）
    assert len(created_urls) == 1
    assert "3307" in created_urls[0]
    await config.close()


@pytest.mark.asyncio
async def test_mysql_database_orm_session_write_primary(monkeypatch):
    """默认 orm_session（写路径）绑定主库引擎"""
    import web_infra.capabilities.db.mysql_config as mc

    created_urls: list[str] = []
    _make_fake_create_async_engine(monkeypatch, created_urls)

    config = mc.MySQLConfig(
        url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app",
        replica_urls=["mysql+aiomysql://root:pwd@127.0.0.1:3307/app"],
    )
    db = MySQLDatabase(config)
    async with db.orm_session() as session:
        await session.execute(text("SELECT 1"))
    assert len(created_urls) == 1
    assert "3306" in created_urls[0]  # 写走主库
    assert config._replica_engines == {}  # 从库引擎未创建
    await config.close()


@pytest.mark.asyncio
async def test_mysql_database_orm_session_read_replica_fallback(monkeypatch):
    """未配置从库时 read_replica=True 回退主库（仅创建主库引擎）"""
    import web_infra.capabilities.db.mysql_config as mc

    created_urls: list[str] = []
    _make_fake_create_async_engine(monkeypatch, created_urls)

    config = mc.MySQLConfig(url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app")
    db = MySQLDatabase(config)
    async with db.orm_session(read_replica=True) as session:
        await session.execute(text("SELECT 1"))
    assert len(created_urls) == 1
    assert "3306" in created_urls[0]  # 回退主库
    await config.close()


@pytest.mark.asyncio
async def test_mysql_database_close_releases_replicas(monkeypatch):
    """MySQLDatabase.close 级联释放从库引擎"""
    import web_infra.capabilities.db.mysql_config as mc

    created_urls: list[str] = []
    _make_fake_create_async_engine(monkeypatch, created_urls)

    config = mc.MySQLConfig(
        url="mysql+aiomysql://root:pwd@127.0.0.1:3306/app",
        replica_urls=["mysql+aiomysql://root:pwd@127.0.0.1:3307/app"],
    )
    db = MySQLDatabase(config)
    async with db.orm_session(read_replica=True):
        pass
    assert config._replica_engines
    await db.close()
    assert config._replica_engines == {}
    assert config._replica_session_factories == {}
