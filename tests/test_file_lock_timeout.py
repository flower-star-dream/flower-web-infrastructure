"""
文件锁超时单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证规范 §16.2：FileLock 支持获取超时——锁空闲时 acquire 立即成功，
              锁被占用时 acquire(timeout) 超时返回 False、上下文管理器入口抛 TimeoutError。
              线程测试注意锁释放顺序，统一用 try/finally 保证不残留持锁线程。
"""
import threading
import time
from pathlib import Path

import pytest

from web_infra.infra.utils.file_lock import FileLock


def _lock_path(tmp_path: Path) -> Path:
    """测试用锁文件路径"""
    return tmp_path / "test.lock"


def test_acquire_succeeds_when_free(tmp_path):
    """锁空闲时 acquire 立即成功并返回 True"""
    fl = FileLock(_lock_path(tmp_path))
    try:
        assert fl.acquire(timeout=0.5) is True
    finally:
        fl.release()


def test_acquire_times_out_when_held_by_other_thread(tmp_path):
    """锁被另一线程占用时 acquire(timeout=0.1) 超时返回 False（规范 §16.2）"""
    lock_path = _lock_path(tmp_path)
    holder_acquired = threading.Event()
    release_holder = threading.Event()
    holder_errors: list[Exception] = []

    def _holder() -> None:
        """持锁线程：获取锁后等待释放信号，期间释放信号前不退出"""
        try:
            with FileLock(lock_path, timeout=2.0):
                holder_acquired.set()
                release_holder.wait(3.0)
        except Exception as exc:  # noqa: BLE001 - 收集线程内异常用于断言
            holder_errors.append(exc)

    thread = threading.Thread(target=_holder, name="file-lock-holder")
    thread.start()
    fl = FileLock(lock_path)
    try:
        assert holder_acquired.wait(3.0), "持锁线程未在预期时间内获取锁"
        start = time.monotonic()
        assert fl.acquire(timeout=0.1) is False
        assert time.monotonic() - start >= 0.05, "超时返回过快，未实际等待"
    finally:
        # 无论断言是否失败，都通知持锁线程释放并等待其退出，避免锁残留影响其他用例
        release_holder.set()
        thread.join(3.0)
        fl.release()
    assert not holder_errors, f"持锁线程异常: {holder_errors}"


def test_context_manager_times_out_when_held(tmp_path):
    """上下文管理器在锁被占用且超时时抛 TimeoutError"""
    lock_path = _lock_path(tmp_path)
    outer = FileLock(lock_path)
    try:
        assert outer.acquire(timeout=0.5) is True
        with pytest.raises(TimeoutError):
            with FileLock(lock_path, timeout=0.1):
                pass  # 超时不应进入临界区
    finally:
        outer.release()


def test_context_manager_succeeds_when_free(tmp_path):
    """上下文管理器在锁空闲时正常进入与释放"""
    with FileLock(_lock_path(tmp_path), timeout=0.5):
        pass
