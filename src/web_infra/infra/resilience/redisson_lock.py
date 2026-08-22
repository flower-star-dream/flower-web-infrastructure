"""
Redisson 风格分布式锁（RLock）

@Author: 花海
@Date: 2026/08/22 20:00
@Description: 自研 Redisson 风格 RLock（对标 Redisson RLock 语义）：在 Redis SET NX PX 基础上叠加
              看门狗自动续期与可重入。看门狗为后台 asyncio Task（每 lease_time/3 秒 PEXPIRE 续期，
              asyncio.shield 保护续期不被取消打断）；可重入用 ContextVar 记录持有者 + 引用计数。
              取消安全约定：release 先同步 cancel 看门狗 Task，再用 asyncio.shield 保护 Lua 删锁，
              最后 await 看门狗并吞掉 CancelledError（避免级联取消导致删锁执行不到）。
              看门狗任务经类级注册表 _active_watchdogs 跟踪，供 Application 停机 shutdown_all_watchdogs 统一清理。
"""
from __future__ import annotations

import asyncio
import secrets
import threading
from contextvars import ContextVar
from typing import Any

from web_infra.infra.constants import CacheKeyBuilder

#: Lua 释放脚本：仅当持有者 token 匹配时才删除（防误删他人新持有的锁）
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

#: 活跃看门狗任务集合（类级锁保护；供停机清理）
_active_watchdogs: set["asyncio.Task[None]"] = set()
_watchdogs_lock = threading.Lock()

#: 可重入持有者上下文（三元组）：记录当前 asyncio 任务持有的锁 Key、token 与引用计数。
#: 值为 (lock_key, token, reentry_count)；无持有者为 ("", "", 0)。
#: 设计（方案甲，工厂按 key 缓存实例保证"同一锁 Key 复用同一 RedissonLock"）：
#:   - lock_key 分量区分不同锁的同任务嵌套（锁 A 内嵌锁 B 不互相误判）；
#:   - token 分量与 self._token 双重校验，兜底"同 Key 多实例"历史遗留调用（防御性，非主路径）；
#:   - count 分量记录重入次数，归零才真正删锁。
_REENTRANT: ContextVar[tuple[str, str, int]] = ContextVar("web_infra_lock_reentrant", default=("", "", 0))


def _track(watchdog: "asyncio.Task[None]") -> None:
    """登记看门狗任务到位集合（done 时自动移除，防孤儿任务无限增长）。"""
    with _watchdogs_lock:
        _active_watchdogs.add(watchdog)
    watchdog.add_done_callback(_discard_watchdog)


def _discard_watchdog(watchdog: "asyncio.Task[None]") -> None:
    """看门狗任务完成回调：从活跃集合移除（持锁，与 _track 保持一致的线程安全）。"""
    with _watchdogs_lock:
        _active_watchdogs.discard(watchdog)


async def shutdown_all_watchdogs() -> None:
    """清理全部活跃看门狗任务（Application 停机时调用；幂等）。

    取消并等待所有残留看门狗退出，避免退出期 flush 一个即将废弃的锁、
    以及 "Task was destroyed but it is pending" 警告与孤儿续期导致死锁窗口永久化。
    """
    with _watchdogs_lock:
        watchdogs = list(_active_watchdogs)
    for w in watchdogs:
        w.cancel()
    if watchdogs:
        await asyncio.gather(*watchdogs, return_exceptions=True)


class RedissonLock:
    """Redisson 风格 RLock（看门狗自动续期 + 可重入，实现 DistributedLockInterface）

    前置约束（方案甲）：同一锁 Key 必须复用同一 RedissonLock 实例（由装配层
    `app.state.distributed_lock` 工厂按完整锁 Key 缓存保证）。实例级可变状态
    `self._token`（真实持有者）在"同 Key 单实例 + Redis SET NX 互斥"前提下
    串行化，无并发竞争；可重入判定依赖此前提，业务勿直接 new 同 Key 多实例。
    """

    def __init__(
        self,
        redis: Any,
        key: str,
        lease_time: int = 30,
        *,
        watchdog_interval: float | None = None,
        lock_name: str | None = None,
    ) -> None:
        """初始化 Redisson 风格 RLock。

        :param redis: redis.asyncio.Redis 兼容客户端（需提供 set/pexpire/eval/delete）
        :param key: 锁业务 Key（自动拼缓存 Key 前缀与版本）
        :param lease_time: 租约时长（秒），看门狗按 lease_time/3 续期；默认 30s
        :param watchdog_interval: 看门狗续期间隔（秒），None 时默认 lease_time/3
        :param lock_name: 看门狗任务命名（便于观测；默认 "redisson-lock:<key>"）
        """
        if lease_time <= 0:
            raise ValueError("lease_time 必须大于 0")
        self._redis = redis
        self._lock_key = CacheKeyBuilder.build(CacheKeyBuilder.DISTRIBUTED_LOCK, key=key)
        self._lease_time = lease_time
        self._watchdog_interval = watchdog_interval or (lease_time / 3.0)
        self._watchdog: asyncio.Task[None] | None = None
        self._lock_name = lock_name or f"redisson-lock:{key}"
        self._token: str | None = None

    @property
    def lock_key(self) -> str:
        """锁对应的完整 Key"""
        return self._lock_key

    async def acquire(self, wait_timeout: float = 3.0) -> bool:
        """尝试获取锁，最多等待 wait_timeout 秒（tryLock）。

        可重入（方案甲）：若当前任务已持有本锁（`_REENTRANT` 的 lock_key 与 `self._lock_key` 一致，
        且 token 与 `self._token` 一致——双重校验兜底同 Key 多实例），引用计数 +1 直接返回 True，
        不重复加锁/不新增看门狗。否则走 Redis `SET NX PX` 加锁并启动看门狗。

        :param wait_timeout: 获取锁的最大等待时长（秒）
        :return: 是否获取成功
        """
        owner, token, count = _REENTRANT.get()
        if self._is_reentrant(owner, token):
            _REENTRANT.set((owner, token, count + 1))
            return True

        token = secrets.token_urlsafe(16)
        deadline = asyncio.get_running_loop().time() + wait_timeout
        while True:
            acquired = await self._redis.set(
                self._lock_key,
                token,
                nx=True,
                px=int(self._lease_time * 1000),
            )
            if acquired:
                self._token = token  # 实例级持有 token（真实持有者，供看门狗续期/删锁用）
                self._start_watchdog()
                _REENTRANT.set((self._lock_key, token, 1))
                if self._watchdog is not None:
                    self._watchdog.set_name(self._lock_name + f":{token[:8]}")  # 便于观测归属
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.05)

    def _is_reentrant(self, owner: str, token: str) -> bool:
        """判断当前任务对 `self._lock_key` 是否可重入（方案甲：单实例前提下的双校验）。

        双校验原因：工厂按 key 缓存实例后，同一锁 Key 只会有一个 RedissonLock，
        `owner == self._lock_key` 已足够判定重入；`token == self._token` 作为防御性兜底，
        兼容历史遗留"同 Key 直接 new 多个实例"的调用，避免误判重入（未真正加锁却返回 True）。

        :param owner: 当前上下文登记的锁 Key 分量
        :param token: 当前上下文登记的 token 分量
        """
        return owner == self._lock_key and bool(token) and token == self._token

    async def release(self) -> None:
        """释放锁（可重入：引用计数递减；归零才真正删锁并取消看门狗；取消安全）。

        计数归零后才真正删除锁（Lua 校验 token）并取消看门狗；中途释放（count>1）
        仅递减计数，锁与看门狗仍保留。未持有（防御性）直接返回。
        """
        owner, token, count = _REENTRANT.get()
        if not owner or owner != self._lock_key:
            return  # 未持有：防御性返回（非同一锁 Key 不释放）
        if count > 1:
            _REENTRANT.set((owner, token, count - 1))
            return
        _REENTRANT.set(("", "", 0))
        self._stop_watchdog()
        try:
            await asyncio.shield(self._release_inner())
        except asyncio.CancelledError:
            raise  # shield 保护的删锁协程在后台继续执行，不在此处中断删锁
        finally:
            self._token = None  # 删锁完成后才清空实例 token（Lua 需据此匹配持有者）

    async def _release_inner(self) -> None:
        """执行 Lua 删除锁（仅持有者 token 匹配；由 shield 保护在取消下也完整执行）。

        注意：删锁 token 取自实例级 self._token（acquire 记录，删锁前保持最初持有 token），
        不依赖 ContextVar——归零时 _REENTRANT 已清空，必须从 self._token 取，Lua 才能正确匹配。
        此处先把 token 快照到局部变量，避免删锁协程被 shield 挂起期间 release 的 finally 清空 token。
        """
        token = self._token
        if not token:
            return
        await self._redis.eval(_RELEASE_SCRIPT, 1, self._lock_key, token)

    def _start_watchdog(self) -> None:
        """启动看门狗续期任务（幂等；已启动则不重复创建）。"""
        if self._watchdog is not None and not self._watchdog.done():
            return
        self._watchdog = asyncio.create_task(self._watchdog_loop(), name=self._lock_name)
        _track(self._watchdog)

    def _stop_watchdog(self) -> None:
        """取消看门狗任务（同步 cancel；等待退出并吞掉 CancelledError，避免级联）。"""
        watchdog, self._watchdog = self._watchdog, None
        if watchdog is None:
            return
        watchdog.cancel()

    async def _watchdog_loop(self) -> None:
        """看门狗循环：每 watchdog_interval 秒续期一次（键仍被持有且是我方 token 时）。"""
        try:
            while True:
                await asyncio.sleep(self._watchdog_interval)
                # shield：续期命令不被取消中途打断（完整执行或完全不执行）
                await asyncio.shield(self._renew())
        except asyncio.CancelledError:
            raise  # 重新抛出，让外层 await 正常收到取消

    async def _renew(self) -> None:
        """续期：仅当当前锁值仍是本锁定 token 时延迟过期（防误续他人锁）。

        token 取实例级 self._token（真实持有者），不取 ContextVar——看门狗由 create_task
        创建，ContextVar 对它只是"启动时快照"，会随任务上下文漂移；self._token 由 acquire
        设置/release 归零，是"这把锁当前被谁持有"的唯一事实源，与任务无关、稳定可靠。
        """
        if not self._token:
            return
        try:
            await self._redis.pexpire(self._lock_key, int(self._lease_time * 1000))
        except Exception:  # noqa: BLE001 - 续期失败仅告警，不影响主流程（租约到期自然让锁）
            import logging

            logging.getLogger(__name__).warning("redisson_lock_renew_failed key=%s", self._lock_key)

    async def __aenter__(self) -> "RedissonLock":
        """异步上下文管理器入口：未获取到锁抛 TimeoutError"""
        if not await self.acquire():
            raise TimeoutError(f"获取分布式锁超时: {self._lock_key}")
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """异步上下文管理器出口：释放锁"""
        await self.release()
