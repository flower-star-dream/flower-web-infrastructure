"""
健康检查与指标端点

@Author: 花海
@Date: 2026/08/14 14:00
@Description: 注册健康检查三端点（整改 S19-1，规范 §19.4）：
              - GET /health/live  存活探针：仅返回 UP/200，不探测依赖（K8s livenessProbe / Docker HEALTHCHECK 使用）
              - GET /health/ready 就绪探针：已装配组件连通性探测 + 启动完成，任一组件 DOWN 返回 503（K8s readinessProbe 使用）
              - GET /health       兼容入口：聚合存活与就绪状态（沿用原单一端点行为），建议新部署改用 live/ready
              与 GET /metrics（Prometheus 文本格式暴露指标，规范 §18.1；浏览器返回 HTML 可视化页面，
              内容协商不破坏 Prometheus 采集）。抓取前刷新连接池/Python 运行时推送式指标。
              组件需提供 health_check() 异步方法（DatabaseFactoryInterface 等已内置）。
"""
from __future__ import annotations

import inspect
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

from web_infra.logging import get_logger
from web_infra.monitoring.metrics_html import render_metrics_html, should_render_html
from web_infra.monitoring.runtime_metrics import record_runtime_metrics
from web_infra.web.json_response import BigIntJSONResponse

logger = get_logger("web.health")

HEALTH_STATUS_UP = "UP"
HEALTH_STATUS_DOWN = "DOWN"


async def _probe_component(name: str, component: Any) -> bool:
    """探测单个组件连通性（组件需提供 health_check 方法，无则视为 UP）"""
    method = getattr(component, "health_check", None)
    if not callable(method):
        return True
    try:
        result = method()
        if inspect.isawaitable(result):
            result = await result
        return bool(result)
    except Exception as e:  # 探测异常视为 DOWN，记录日志便于排查
        logger.error("health_component_check_failed component=%s error=%s", name, str(e))
        return False


def _refresh_pushed_metrics(components: dict[str, Any]) -> None:
    """刷新推送式指标（连接池/组件 Gauge 与 Python 运行时）。

    组件提供 update_pool_metrics()（连接池）或 update_metrics()（组件积压/实例数）时
    在 /metrics 抓取前刷新；单次刷新异常不影响指标暴露（记录日志后继续）。
    """
    for component in components.values():
        for method_name in ("update_pool_metrics", "update_metrics"):
            method = getattr(component, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception as e:
                    logger.warning("metrics_refresh_failed method=%s error=%s", method_name, str(e))
    record_runtime_metrics()


async def _probe_components(components: dict[str, Any]) -> tuple[dict[str, str], bool]:
    """探测全部组件连通性（供 /health/ready 与兼容入口 /health 复用）。

    :param components: 已装配组件字典（name -> component）
    :return: (组件状态字典, 是否全部健康)
    """
    statuses: dict[str, str] = {}
    all_healthy = True
    for name, component in components.items():
        ok = await _probe_component(name, component)
        statuses[name] = HEALTH_STATUS_UP if ok else HEALTH_STATUS_DOWN
        if not ok:
            all_healthy = False
    return statuses, all_healthy


def register_health_endpoints(
    app: FastAPI,
    components: dict[str, Any] | None = None,
    service_name: str = "web-infra",
    enable_metrics: bool = True,
) -> None:
    """注册健康检查与指标端点。

    :param app: FastAPI 应用实例
    :param components: 已装配组件字典（name -> component），探测其 health_check 连通性
    :param service_name: 健康检查响应中的 service 字段
    :param enable_metrics: 是否注册 /metrics 端点（默认开启）
    """
    components = components or {}

    @app.get("/health/live")
    async def health_live() -> BigIntJSONResponse:
        """存活探针（规范 §19.4，整改 S19-1）：仅返回进程存活状态。

        不探测任何依赖（组件 DOWN 不影响存活判定），供 Docker HEALTHCHECK / K8s livenessProbe 使用。
        """
        return BigIntJSONResponse(
            status_code=200,
            content={"status": HEALTH_STATUS_UP, "service": service_name},
        )

    @app.get("/health/ready")
    async def health_ready() -> BigIntJSONResponse:
        """就绪探针（规范 §19.4，整改 S19-1）：依赖连通性探测 + 启动完成。

        端点由应用装配（build）最后一步注册，可达即代表应用启动完成；
        任一组件 DOWN 返回 503，供 K8s readinessProbe 使用（就绪失败不摘除存活）。
        """
        statuses, all_healthy = await _probe_components(components)
        return BigIntJSONResponse(
            status_code=200 if all_healthy else 503,
            content={
                "status": HEALTH_STATUS_UP if all_healthy else HEALTH_STATUS_DOWN,
                "service": service_name,
                "components": statuses,
            },
        )

    @app.get("/health")
    async def health_check() -> BigIntJSONResponse:
        """兼容入口（规范 §19.4）：聚合存活与就绪状态，沿用原单一端点行为。

        注意：建议新部署改用 /health/live（存活）与 /health/ready（就绪）分离探活。
        """
        statuses, all_healthy = await _probe_components(components)
        return BigIntJSONResponse(
            status_code=200 if all_healthy else 503,
            content={
                "status": HEALTH_STATUS_UP if all_healthy else HEALTH_STATUS_DOWN,
                "service": service_name,
                "components": statuses,
            },
        )

    if enable_metrics:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        @app.get("/metrics")
        async def metrics_endpoint(request: Request, format: str | None = None) -> Response:
            """指标暴露端点（规范 §18.1）：内容协商返回。

            浏览器（Accept 含 text/html）返回格式化 HTML 可视化页面，
            可通过 ?format=html / ?format=text 强制指定格式；
            Prometheus 抓取返回 OpenMetrics 文本，不破坏监控采集。
            """
            # 抓取前刷新推送式指标（连接池 / Python 运行时）
            _refresh_pushed_metrics(components)
            if should_render_html(format, request.headers.get("accept")):
                return HTMLResponse(render_metrics_html(service_name))
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
