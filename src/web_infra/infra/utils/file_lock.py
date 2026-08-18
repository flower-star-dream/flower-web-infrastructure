"""
跨平台文件锁

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于操作系统文件锁的上下文管理器，保护多进程/多线程并发写同一文件。
              POSIX 用 fcntl.flock，Windows 用 msvcrt.locking，不支持时退化为线程锁。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path


class _NoOpLock:
    """退化实现：仅保护同进程内并发"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._acquired = False

    def acquire(self, timeout: float | None = None) -> bool:
        """获取锁；timeout 秒内未获取到返回 False（None 保持阻塞，规范 §16.2）"""
        if timeout is None:
            self._lock.acquire()
        elif not self._lock.acquire(timeout=timeout):
            return False
        self._acquired = True
        return True

    def release(self) -> None:
        """释放锁；未持有锁时为安全的 no-op（与 FileLock.release 契约一致）"""
        if self._acquired:
            self._lock.release()
            self._acquired = False


class _FcntlLock:
    """POSIX 文件锁实现"""

    def __init__(self, lock_path: Path) -> None:
        import fcntl

        self._lock_path = lock_path
        self._lock_file: int | None = None
        self._fcntl = fcntl

    def acquire(self, timeout: float | None = None) -> bool:
        """获取文件锁；timeout 秒内未获取到返回 False（None 保持阻塞，规范 §16.2）。

        带超时实现：非阻塞尝试（LOCK_NB）+ 轮询，超时未获取则关闭句柄并返回 False，避免句柄泄漏。
        """
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT, 0o666)
        if timeout is None:
            self._fcntl.flock(self._lock_file, self._fcntl.LOCK_EX)
            return True
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._fcntl.flock(self._lock_file, self._fcntl.LOCK_EX | self._fcntl.LOCK_NB)
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(self._lock_file)
                    self._lock_file = None
                    return False
                time.sleep(0.01)

    def release(self) -> None:
        """释放文件锁并关闭句柄"""
        if self._lock_file is not None:
            try:
                self._fcntl.flock(self._lock_file, self._fcntl.LOCK_UN)
            finally:
                os.close(self._lock_file)
                self._lock_file = None


class _MsvcrtLock:
    """Windows 文件锁实现"""

    def __init__(self, lock_path: Path) -> None:
        import msvcrt

        self._lock_path = lock_path
        self._lock_file: int | None = None
        self._msvcrt = msvcrt

    def acquire(self, timeout: float | None = None) -> bool:
        """获取文件锁；timeout 秒内未获取到返回 False（None 保持阻塞，规范 §16.2）。

        带超时实现：非阻塞尝试（LK_NBLCK）+ 轮询，超时未获取则关闭句柄并返回 False，避免句柄泄漏。
        """
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file = os.open(str(self._lock_path), os.O_RDWR | os.O_CREAT, 0o666)
        if timeout is None:
            self._msvcrt.locking(self._lock_file, self._msvcrt.LK_LOCK, 1)
            return True
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._msvcrt.locking(self._lock_file, self._msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(self._lock_file)
                    self._lock_file = None
                    return False
                time.sleep(0.01)

    def release(self) -> None:
        """释放文件锁并关闭句柄"""
        if self._lock_file is not None:
            try:
                self._msvcrt.locking(self._lock_file, self._msvcrt.LK_UNLCK, 1)
            finally:
                os.close(self._lock_file)
                self._lock_file = None


def _create_lock(lock_path: Path):
    """按平台选择文件锁实现"""
    try:
        import fcntl  # noqa: F401

        return _FcntlLock(lock_path)
    except ImportError:
        pass
    try:
        import msvcrt  # noqa: F401

        return _MsvcrtLock(lock_path)
    except ImportError:
        pass
    return _NoOpLock()


class FileLock:
    """跨平台文件锁上下文管理器（规范 §16.2：锁必须带超时）"""

    def __init__(self, lock_path: str | Path, *, timeout: float | None = None) -> None:
        self._lock_path = Path(lock_path)
        self._lock = _create_lock(self._lock_path)
        self._timeout = timeout

    def acquire(self, timeout: float | None = None) -> bool:
        """获取文件锁；timeout 秒内未获取到返回 False（None 保持阻塞）。

        未显式传 timeout 时回退到构造参数 timeout（规范 §16.2：3s 获取上限由调用方约束）。
        超时未获取到锁返回 False，由调用方决定重试或放弃（上下文管理器入口会抛 TimeoutError）。
        """
        if timeout is None:
            timeout = self._timeout
        return self._lock.acquire(timeout=timeout)

    def release(self) -> None:
        """释放文件锁（未持有锁时为安全的 no-op）"""
        self._lock.release()

    def __enter__(self) -> "FileLock":
        """进入上下文时获取锁；超时未获取抛 TimeoutError（规范 §16.2）"""
        if not self.acquire(timeout=self._timeout):
            raise TimeoutError(f"获取文件锁超时: {self._lock_path}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """退出上下文时释放锁，异常原样传播"""
        self._lock.release()
        return False
