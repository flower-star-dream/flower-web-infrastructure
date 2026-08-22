"""
测试全局隔离夹具

@Author: 花海
@Date: 2026/08/22 21:30
@Description: 统一清理跨测试的全局状态，避免顺序依赖污染（test_health 等「无请求样本不渲染
              HTTP RED 分组」断言、生命周期/HTTP/认证事件的监听器残留、模块级事件总线持有器）：
              - Prometheus 全局指标：HTTP RED 组（http_requests_total / http_request_errors_total /
                http_request_duration_seconds / http_requests_in_flight）与阶段耗时直方图；
              - 模块级事件总线持有器（_current_event_bus，供无 app 引用的框架组件发布）；
              - 事件监听器注册表（EventListenerRegistry，防止残留监听器触发后续应用生命周期事件）。
              每个用例结束后执行；与各测试文件内既有清理夹具（test_client_ip/_clean_red_metrics、
              test_event_bus/_event_bus_holder_cleanup）兼容（重复清理幂等，无副作用）。
              框架不在导入时自动注册监听器（@event_listener 仅由业务/测试运行时注册），故清空安全。
"""
from __future__ import annotations

import pytest

from web_infra.infra.monitoring import metrics


@pytest.fixture(autouse=True)
def _global_test_isolation():
    """统一清理全局指标与事件总线状态（每个用例结束后执行）。

    事件总线核心化后：每次 create_app 都会设置模块级总线持有器、应用停机会发布生命周期事件；
    经 LoggingMiddleware 的请求会写入全局 HTTP RED 指标。这些全局态跨测试累积会导致
    test_health 等「无请求样本不渲染 HTTP RED 分组」断言被顺序污染，故统一在用例后清空。
    """
    yield
    # 清空 HTTP RED 组指标（该分组由这 4 个指标构成，见 metrics_html 分组定义）+ 阶段耗时直方图
    metrics.HTTP_REQUESTS_TOTAL.clear()
    metrics.HTTP_REQUEST_ERRORS_TOTAL.clear()
    metrics.HTTP_REQUEST_DURATION_SECONDS.clear()
    metrics.HTTP_REQUESTS_IN_FLIGHT.clear()
    metrics.REQUEST_PHASE_DURATION_SECONDS.clear()
    # 清空模块级事件总线持有器与事件监听器注册表
    from web_infra.capabilities.event import clear_current_event_bus
    from web_infra.capabilities.event.listener_registry import EventListenerRegistry

    clear_current_event_bus()
    EventListenerRegistry.clear()
