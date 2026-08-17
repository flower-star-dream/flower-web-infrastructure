"""
统一日志中间件

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 记录请求进入/离开、耗时、状态码、TraceId，采集 RED 指标（§18.1）与分阶段耗时（§18.5.1）。
"""
from __future__ import annotations

import re
import time
import uuid

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from web_infra.constants import AUTH_HEADER_TRACE_ID, HttpStatusConstant
from web_infra.constants.sys_constant import SysConstant
from web_infra.context import RequestContext
from web_infra.logging import get_logger
from web_infra.logging.masking import mask
from web_infra.monitoring.metrics import HTTP_REQUESTS_IN_FLIGHT, SLOW_REQUEST_TOTAL, record_http_request
from web_infra.monitoring.phase_timer import PhaseTimer
from web_infra.monitoring.slow_request_store import SlowRequestStore

# TraceId 请求头名（统一管理于 web_infra.constants）
TRACE_ID_HEADER = AUTH_HEADER_TRACE_ID

# 路径归一化：UUID/数字 ID 段替换为 {id}，避免指标标签携带高基数动态值（§18.1）
_PATH_ID_SEGMENT_RE = re.compile(r"/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|/\d+")

# 慢请求样本参数摘要最大长度（防超长参数撑爆内存/日志）
_PARAM_SUMMARY_MAX_LEN = 500


def _slow_sample_params_summary(request: Request) -> str:
    """生成慢请求样本的请求参数摘要（脱敏 + 截断，规范 §17.3）。

    :param request: 当前请求
    :return: 脱敏后的 query 参数摘要；无参数时返回 "-"
    """
    summary = mask(str(request.query_params))
    return summary[: _PARAM_SUMMARY_MAX_LEN] or "-"


def _record_slow_sample(
    *,
    trace_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    params: str,
    phases: dict[str, float],
) -> None:
    """写入一条慢请求样本到有界环形缓存（供运维回放，§18.5.2）。

    :param trace_id: 链路 TraceId
    :param method: HTTP 方法
    :param path: 归一化脱敏路径（UUID/数字段已替换为 {id}）
    :param status_code: 响应状态码
    :param duration_ms: 请求总耗时（毫秒）
    :param params: 脱敏后的请求参数摘要
    :param phases: 各阶段耗时字段（phase_timer.to_log_fields() 输出）
    """
    SlowRequestStore.instance().record({
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "trace_id": trace_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 1),
        "params": params,
        "phases": phases,
    })


class LoggingMiddleware(BaseHTTPMiddleware):
    """FastAPI 访问日志中间件"""

    def __init__(self, app: ASGIApp, service_name: str = "app") -> None:
        super().__init__(app)
        self.logger = get_logger(f"{service_name}.access")
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """处理请求生命周期：注入 TraceId、启动阶段埋点、记录访问日志与 RED 指标"""
        trace_id = request.headers.get(TRACE_ID_HEADER, str(uuid.uuid4()))
        request.state.trace_id = trace_id
        RequestContext.set_trace_id(trace_id)
        phase_timer = PhaseTimer.start()

        start_time = time.perf_counter()
        method = request.method
        path = request.url.path
        metric_path = _PATH_ID_SEGMENT_RE.sub("/{id}", path)
        HTTP_REQUESTS_IN_FLIGHT.labels(service=self.service_name).inc()
        client_ip = request.client.host if request.client else "-"

        self.logger.info("request_in trace_id=%s method=%s path=%s client_ip=%s", trace_id, method, path, client_ip)

        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                duration_ms = (time.perf_counter() - start_time) * 1000
                phase_timer.mark_total()
                record_http_request(method, metric_path, duration_ms / 1000.0, 500, is_error=True, service=self.service_name)
                self.logger.error("request_exception trace_id=%s path=%s error=%s", trace_id, path, str(exc))
                raise

            duration_ms = (time.perf_counter() - start_time) * 1000
            status_code = response.status_code
            response.headers[TRACE_ID_HEADER] = trace_id
            phase_timer.mark_total()
            phase_timer.record_metrics(service=self.service_name)
            record_http_request(method, metric_path, duration_ms / 1000.0, status_code, service=self.service_name)

            if duration_ms > SysConstant.SYS_SLOW_REQUEST_THRESHOLD_MS:
                SLOW_REQUEST_TOTAL.labels(service=self.service_name, path=metric_path).inc()
                _record_slow_sample(
                    trace_id=trace_id,
                    method=method,
                    path=metric_path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    params=_slow_sample_params_summary(request),
                    phases=phase_timer.to_log_fields(),
                )

            user_id = RequestContext.get_user_id()
            log_level = (
                "error"
                if status_code >= HttpStatusConstant.HTTP_SERVER_ERROR_MIN
                else "warning"
                if status_code >= HttpStatusConstant.HTTP_CLIENT_ERROR_MIN or duration_ms > SysConstant.SYS_SLOW_REQUEST_THRESHOLD_MS
                else "info"
            )
            phase_fields = " ".join(f"{k}={v}" for k, v in phase_timer.to_log_fields().items())
            getattr(self.logger, log_level)(
                "request_out trace_id=%s method=%s path=%s status=%s duration_ms=%.3f user_id=%s %s",
                trace_id, method, path, status_code, duration_ms, user_id, phase_fields,
            )
            return response
        finally:
            HTTP_REQUESTS_IN_FLIGHT.labels(service=self.service_name).dec()
            PhaseTimer.clear()


def setup_logging_middleware(app: FastAPI, service_name: str = "app") -> None:
    """注册访问日志中间件"""
    app.add_middleware(LoggingMiddleware, service_name=service_name)
