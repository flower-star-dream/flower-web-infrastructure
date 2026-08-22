"""
分布式锁（兼容层）

@Author: 花海
@Date: 2026/08/22 20:00
@Description: 兼容层：re-export Redis 分布式锁实现 `DistributedLock`，保持旧模块级导入路径
              `web_infra.infra.resilience.distributed_lock` 与包级导入不被破坏。
              新代码建议经 `DistributedLockRegistry` 按 type 装配，或直接导入
              `web_infra.infra.resilience.redis_distributed_lock.DistributedLock`。
"""
from web_infra.infra.resilience.redis_distributed_lock import DistributedLock  # noqa: F401

__all__ = ["DistributedLock"]
