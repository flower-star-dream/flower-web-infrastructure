"""
优雅停机单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证规范 §19.2 优雅停机等待窗口：默认 wait=0 关闭立即完成（保持旧行为与测试兼容），
              配置 wait>0 时先执行等待窗口（sleep）再关闭组件（摘流量→等待窗口→连接排空→优雅退出）；
              组件 close/stop 原有调用语义不变。
"""
import pytest

from web_infra.core.application import Application


class _CloseRecorder:
    """记录 close 调用的假组件"""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_shutdown_completes_immediately_with_default_wait():
    """默认未配置等待窗口：关闭立即完成（不 sleep），组件 close 正常执行"""
    app = Application({"app.name": "test-app"})
    recorder = _CloseRecorder()
    app._components = {"dummy": recorder}
    await app._shutdown()
    assert recorder.closed is True


@pytest.mark.asyncio
async def test_shutdown_waits_zero_does_not_sleep(monkeypatch):
    """显式 wait=0：不调用 sleep（测试兼容，生产建议配置 >0）"""
    import web_infra.core.application as app_module

    slept = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(app_module.asyncio, "sleep", _fake_sleep)

    app = Application({"app.graceful_shutdown_wait_seconds": 0})
    recorder = _CloseRecorder()
    app._components = {"dummy": recorder}
    await app._shutdown()
    assert slept == []
    assert recorder.closed is True


@pytest.mark.asyncio
async def test_shutdown_waits_window_before_close(monkeypatch):
    """配置 wait>0：先执行等待窗口（sleep 窗口时长），再关闭组件（规范 §19.2 顺序）"""
    import web_infra.core.application as app_module

    slept = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(app_module.asyncio, "sleep", _fake_sleep)

    app = Application({"app.graceful_shutdown_wait_seconds": 10.0})
    recorder = _CloseRecorder()
    app._components = {"dummy": recorder}
    await app._shutdown()
    assert slept == [10.0]
    assert recorder.closed is True


@pytest.mark.asyncio
async def test_shutdown_calls_stop_when_component_has_no_close(monkeypatch):
    """组件仅提供 stop 时同样被关闭（原有关闭语义不变）"""
    import web_infra.core.application as app_module

    async def _fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(app_module.asyncio, "sleep", _fake_sleep)

    class _StopRecorder:
        def __init__(self) -> None:
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    app = Application({"app.name": "test-app"})
    recorder = _StopRecorder()
    app._components = {"dummy": recorder}
    await app._shutdown()
    assert recorder.stopped is True
