"""
分布式锁 SPI 与 Redisson RLock 测试

@Author: 花海
@Date: 2026/08/22 20:00
@Description: 验证分布式锁抽象接口、注册表（按 type 装配）、RedissonLock 看门狗续期、
              可重入、取消安全与看门狗注册表清理。使用内存 FakeRedis 模拟 redis.asyncio 语义。
"""
import asyncio
import pytest

from web_infra.infra.resilience.distributed_lock_registry import DistributedLockRegistry
from web_infra.infra.resilience.distributed_lock_interface import DistributedLockInterface
from web_infra.infra.resilience.redisson_lock import RedissonLock, _active_watchdogs, shutdown_all_watchdogs


def test_registry_register_and_names():
    """注册表：register 后 registered_names 可见，get 可取工厂"""
    class _FakeLock:
        """最小锁占位（实现接口）"""

        async def acquire(self, wait_timeout: float = 3.0) -> bool:
            return True

        async def release(self) -> None:
            return None

        @property
        def lock_key(self) -> str:
            return "fake"

    DistributedLockRegistry.register("fake", lambda key, lease_time=30: _FakeLock())
    assert "fake" in DistributedLockRegistry.registered_names()
    factory = DistributedLockRegistry.get("fake")
    assert callable(factory)
    DistributedLockRegistry.unregister("fake")


def test_interface_runtime_checkable():
    """接口可做 isinstance 运行时校验（同 IdempotencyStoreInterface 风格）"""
    assert DistributedLockInterface is not None

    class _Minimal:
        async def acquire(self, wait_timeout: float = 3.0) -> bool:
            return True

        async def release(self) -> None:
            return None

        @property
        def lock_key(self) -> str:
            return "x"

        async def __aenter__(self) -> "_Minimal":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    assert isinstance(_Minimal(), DistributedLockInterface)


class _FakeRedis:
    """模拟 redis.asyncio：set(nx/px)、pexpire、eval、delete；时钟可注入以测续期"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}  # key -> (token, expire_at_ms)
        self._now_ms: float = 0.0
        self.pexpire_calls: list[tuple[str, int]] = []

    def advance(self, ms: float) -> None:
        """推进模拟时钟（毫秒）"""
        self._now_ms += ms

    def _purge(self, key: str) -> None:
        item = self._store.get(key)
        if item and item[1] <= self._now_ms:
            del self._store[key]

    async def set(self, key: str, value: str, nx: bool = False, px: int | None = None) -> bool:
        self._purge(key)
        if nx and key in self._store:
            return False
        exp = (self._now_ms + px) if px is not None else float("inf")
        self._store[key] = (value, exp)
        return True

    async def pexpire(self, key: str, ms: int) -> bool:
        self.pexpire_calls.append((key, ms))
        item = self._store.get(key)
        if item:
            self._store[key] = (item[0], self._now_ms + ms)
            return True
        return False

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        self._purge(key)
        item = self._store.get(key)
        if item and item[0] == token:
            del self._store[key]
            return 1
        return 0

    async def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0


class _GatedEvalRedis(_FakeRedis):
    """延迟删除版 FakeRedis：eval 先挂起在 gate 上，由测试控制何时真正执行删锁。

    用于复现 shield 竞态：release 外层被取消（finally 清空 self._token）时，
    删锁协程已把 token 快照进局部变量并挂在 eval 上——即使 self._token 随后被清空，
    删锁仍用快照 token 完成，不会因 token 失配而删不掉锁。
    """

    def __init__(self) -> None:
        super().__init__()
        self.eval_started = asyncio.Event()  # 已进入 eval（token 已快照）
        self.eval_gate = asyncio.Event()     # 测试放行后才真正删锁

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        self.eval_started.set()
        await self.eval_gate.wait()  # 挂起：模拟删锁请求在网络中延迟（shield 挂起窗口）
        return await super().eval(script, numkeys, key, token)


@pytest.mark.asyncio
async def test_redisson_lock_acquire_and_watchdog_renews():
    """看门狗：获取锁后持续续期（pexpire），不因静态租约过期而丢失锁"""
    redis = _FakeRedis()
    lock = RedissonLock(redis, key="biz:1001", lease_time=30)
    assert await lock.acquire(wait_timeout=0.1) is True
    # 推进 35s（超过静态租约 30s），看门狗应已续期使锁仍存在
    redis.advance(35000)
    await asyncio.sleep(0.05)  # 给看门狗机会执行
    assert redis._store.get(lock.lock_key) is not None
    await lock.release()


@pytest.mark.asyncio
async def test_redisson_lock_reentrant_same_lock():
    """可重入：同一任务可重复 acquire，仅首次真正加锁 + 一次看门狗，release 需成对"""
    redis = _FakeRedis()
    lock = RedissonLock(redis, key="biz:1001", lease_time=30)
    assert await lock.acquire(wait_timeout=0.1) is True
    assert await lock.acquire(wait_timeout=0.1) is True  # 可重入，返回 True
    await lock.release()  # 第一次释放：引用计数归 1，锁仍存在
    assert redis._store.get(lock.lock_key) is not None
    await lock.release()  # 第二次释放：归零，真正删锁
    assert redis._store.get(lock.lock_key) is None


@pytest.mark.asyncio
async def test_redisson_lock_cancellation_cleans_watchdog():
    """取消安全：释放锁时取消看门狗，锁被正确删除，看门狗不残留"""
    redis = _FakeRedis()
    lock = RedissonLock(redis, key="biz:1001", lease_time=30)
    assert await lock.acquire(wait_timeout=0.1) is True
    # 已注册到看门狗集合
    assert len(_active_watchdogs) == 1
    await lock.release()
    await asyncio.sleep(0.02)
    # 释放后看门狗应取消并从集合移除
    assert lock.lock_key not in redis._store
    assert len(_active_watchdogs) == 0


@pytest.mark.asyncio
async def test_redisson_lock_release_inner_token_snapshot_on_cancel():
    """shield 竞态（专项，锁死覆盖精度）：release 外层被取消、finally 清空 self._token 时，
    删锁协程仍用【进入 eval 前快照的 token】完成删除——不因 self._token 被清成 None 而 token 失配、
    锁删不掉。若实现回退为"删锁前清 token 且 eval 时读 self._token"，本用例会失败。

    时序由事件门精确控制（不依赖 sleep 竞态）：
    1. acquire 成功，store[key]=tokenA；
    2. 启动 release 协程，_release_inner 已进入 eval（token 已快照为 tokenA）并挂在 gate 上；
    3. 取消 release 外层 → 触发 release.finally 把 self._token 置 None；
    4. 放行 gate → eval 用快照 token 校验匹配 → 删锁成功。
    """
    redis = _GatedEvalRedis()
    lock = RedissonLock(redis, key="biz:1001", lease_time=30)
    assert await lock.acquire(wait_timeout=0.1) is True
    assert redis._store.get(lock.lock_key) is not None

    release_task = asyncio.create_task(lock.release())
    await redis.eval_started.wait()   # 内层已进入 eval、token 已快照、正挂在 gate 上
    # 此刻 self._token 尚未清空，但删锁已用快照 token；取消外层触发释放清理
    release_task.cancel()
    try:
        await release_task
    except asyncio.CancelledError:
        pass
    # 放行 gate，让删锁协程真正执行（此时 self._token 已被 release.finally 清成 None）
    redis.eval_gate.set()
    await asyncio.sleep(0.02)
    # 锁仍被正确删除（用快照 token，而非被清空的 self._token）
    assert lock.lock_key not in redis._store


@pytest.mark.asyncio
async def test_shutdown_all_watchdogs_clears_residuals():
    """停机清理：活跃看门狗被 shutdown_all_watchdogs 全部取消"""
    redis = _FakeRedis()
    lock = RedissonLock(redis, key="biz:1001", lease_time=30)
    await lock.acquire(wait_timeout=0.1)
    await shutdown_all_watchdogs()
    assert len(_active_watchdogs) == 0


def test_default_lock_disabled_unless_enabled():
    """app.lock.enabled 缺省 false：默认 create_app 不装配锁（不强制 Redis，可启动）"""
    from web_infra import create_app

    app = create_app({"app.name": "test-app"})
    assert not hasattr(app.state, "distributed_lock")


def test_lock_enabled_type_is_redisson(monkeypatch):
    """app.lock.enabled=true 时装配分布式锁，app.state.distributed_lock 存在"""
    import web_infra.core.application as application_module

    # 显式启用锁并注入假 Redis 客户端（提供 set/pexpire/eval/delete）走通装配路径
    monkeypatch.setattr(application_module.Application, "_resolve_lock_redis", lambda self: _FakeRedis())
    from web_infra import create_app

    app = create_app({"app.name": "test-app", "app.lock.enabled": True})
    assert hasattr(app.state, "distributed_lock")


def test_lock_enabled_without_redis_fast_fail():
    """app.lock.enabled=true 但无 Redis 客户端：装配期快速失败（ConfigError，不静默回落）"""
    from web_infra import ConfigError, create_app

    with pytest.raises(ConfigError):
        create_app({"app.name": "test-app", "app.lock.enabled": True})


def test_lock_factory_caches_same_key_instance_via_registry():
    """经注册表直连工厂：同 key 的 lock_key 一致（真实同对象复用由装配层缓存保证）"""
    from web_infra.infra.resilience.distributed_lock_registry import DistributedLockRegistry

    factory = DistributedLockRegistry.get("redisson")
    lock1 = factory(_FakeRedis(), key="biz:1001", lease_time=30)
    lock2 = factory(_FakeRedis(), key="biz:1001", lease_time=30)
    assert lock1.lock_key == lock2.lock_key


def test_application_lock_factory_reuses_same_instance(monkeypatch):
    """方案甲：装配层锁工厂同一锁 Key 返回同一 RedissonLock 实例（同对象复用）"""
    import web_infra.core.application as application_module

    monkeypatch.setattr(application_module.Application, "_resolve_lock_redis", lambda self: _FakeRedis())
    from web_infra import create_app

    app = create_app({"app.name": "test-app", "app.lock.enabled": True})
    lock_factory = app.state.distributed_lock
    lock1 = lock_factory("biz:1001")
    lock2 = lock_factory("biz:1001")
    assert lock1 is lock2


def test_application_lock_factory_lru_evicts_oldest(monkeypatch):
    """P1 加固：锁实例缓存超 cache_max_size 上限时按 LRU 淘汰最久未用（防锁 Key 无限增长内存泄漏）"""
    import web_infra.core.application as application_module

    monkeypatch.setattr(application_module.Application, "_resolve_lock_redis", lambda self: _FakeRedis())
    from web_infra import create_app

    # cache_max_size=2：只保留最近使用的前 2 个锁实例
    app = create_app({"app.name": "test-app", "app.lock.enabled": True, "app.lock.cache_max_size": 2})
    lock_factory = app.state.distributed_lock
    # 依次访问 3 个不同锁 Key，触发 LRU 淘汰
    lock_a = lock_factory("biz:a")
    lock_b = lock_factory("biz:b")
    # 再次访问 a，使其变为最近使用（LRU 语义：此时 b 变最久未用）
    lock_a2 = lock_factory("biz:a")
    assert lock_a2 is lock_a
    # 新 Key c 触发淘汰：应淘汰最久未用的 b
    lock_c = lock_factory("biz:c")
    assert lock_c is not lock_b
    # b 已被淘汰；重新取 b 会得到新实例（非旧实例）
    lock_b2 = lock_factory("biz:b")
    assert lock_b2 is not lock_b


def test_top_level_exports_lock_symbols():
    """顶层导出分布式锁符号（保留 DistributedLock 兼容）"""
    import web_infra

    assert web_infra.DistributedLock is not None       # 兼容（Redis 实现）
    assert web_infra.RedissonLock is not None
    assert web_infra.DistributedLockInterface is not None
    assert web_infra.DistributedLockRegistry is not None
