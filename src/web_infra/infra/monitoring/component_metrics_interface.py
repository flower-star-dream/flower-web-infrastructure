"""
组件指标采集器抽象基类

@Author: 花海
@Date: 2026/08/14 23:30
@Description: 框架组件（缓存/存储/消息队列/注册中心等）指标采集器的懒注册基类：
              指标仅在组件实际被调用（即启用）时注册到 REGISTRY；未启用组件不产生任何指标，
              因此 /metrics 文本与 HTML 页面均不会展现——由组件启用配置动态决定指标是否采集。
              子类须声明独立的 _registered/_lock 类属性（保证各组件注册互不影响），
              并在 ensure() 中完成指标定义与注册；组件关闭时调用 unregister_metrics()
              卸载指标并复位状态（规范 §16.5 扩展点注册与生命周期绑定）。
"""
from __future__ import annotations

from threading import Lock
from typing import ClassVar


class ComponentMetricsCollector:
    """组件指标采集器抽象基类（懒注册模式）"""

    _registered: ClassVar[bool] = False
    # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
    _lock: ClassVar[Lock] = Lock()

    @classmethod
    def ensure(cls) -> None:
        """注册组件指标（线程安全，仅首次执行）。

        子类必须实现：首次调用时创建并注册本组件的全部指标，
        且各子类须覆写 _registered/_lock 类属性。
        """
        raise NotImplementedError

    @classmethod
    def unregister_metrics(cls) -> None:
        """卸载本组件已注册的指标（组件关闭时调用，规范 §16.5 扩展点注册与生命周期绑定）。

        子类必须实现：将 ensure() 注册的指标从 prometheus REGISTRY 移除并复位
        _registered 状态，保证组件重启后 ensure() 可重新注册（不抛重名异常）。
        """
        raise NotImplementedError
