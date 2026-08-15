"""
读写分离路由

@Author: 花海
@Date: 2026/08/15 09:00
@Description: 读写分离路由（规范 S10-2：读流量路由从库，写走主库）。
              管理主/从数据源名称，提供从库轮询（round-robin）与读写路由决策；
              线程安全（threading.Lock 保护从库注册表与轮询游标）。
"""
from __future__ import annotations

import threading


class ReadWriteRouter:
    """读写分离路由（S10-2）：维护主/从库名称集合，读路由从库（轮询）、写路由主库"""

    def __init__(self, primary_name: str = "primary") -> None:
        """初始化读写分离路由（默认主库名为 primary）"""
        self._primary_name = primary_name
        self._replica_names: list[str] = []
        self._cursor = 0
        self._lock = threading.Lock()

    def register_replica(self, name: str) -> None:
        """注册单个从库（重复注册幂等，不重复加入轮询）"""
        with self._lock:
            if name not in self._replica_names:
                self._replica_names.append(name)

    def register_replicas(self, names: list[str]) -> None:
        """批量注册从库"""
        for name in names:
            self.register_replica(name)

    def remove_replica(self, name: str) -> None:
        """移除指定从库（不存在时静默）"""
        with self._lock:
            if name in self._replica_names:
                self._replica_names.remove(name)

    def next_replica(self) -> str | None:
        """按轮询（round-robin）返回下一个从库名；无从库时返回 None"""
        with self._lock:
            if not self._replica_names:
                return None
            name = self._replica_names[self._cursor % len(self._replica_names)]
            self._cursor += 1
            return name

    def route(self, operation: str) -> str | None:
        """读写路由决策（S10-2）：read 返回从库名（无从库返回 None），write 返回主库名"""
        if operation == "write":
            return self._primary_name
        if operation == "read":
            return self.next_replica()
        raise ValueError(f"不支持的路由操作: {operation!r}，仅支持 'read'/'write'")
