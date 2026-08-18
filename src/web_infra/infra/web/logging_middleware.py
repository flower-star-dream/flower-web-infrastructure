"""
统一访问日志中间件（接入 uvicorn 日志）

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 记录请求访问日志：输出与 uvicorn 原生访问日志一致的格式（客户端 IP:端口 - "方法 路径 HTTP/版本" 状态码），
              并追加 trace_id / 耗时 / 用户 / 分阶段耗时字段；同时采集 RED 指标（§18.1）与慢请求样本（§18.5）。
              客户端 IP 为真实 IP：经 get_client_ip 解析（仅可信代理透传的 X-Real-IP / X-Forwarded-For 被信任，
              见 client_ip.py），并经 apply_real_client_ip 写回 scope["client"]，保证下游 request.client 读取一致。
              为保持"唯一访问日志"，应用启动阶段关闭 uvicorn 原生访问日志（见 disable_uvicorn_access_log），
              避免与中间件输出重复。
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from web_infra.infra.constants import AUTH_HEADER_TRACE_ID, HttpStatusConstant
from web_infra.infra.constants.sys_constant import SysConstant
from web_infra.infra.context import RequestContext
from web_infra.infra.logging import get_logger
from web_infra.infra.logging.masking import mask
from web_infra.infra.monitoring.metrics import HTTP_REQUESTS_IN_FLIGHT, SLOW_REQUEST_TOTAL, record_http_request
from web_infra.infra.monitoring.phase_timer import PhaseTimer
from web_infra.infra.monitoring.slow_request_store import SlowRequestStore
from web_infra.infra.web.client_ip import apply_real_client_ip, get_client_ip

# TraceId 请求头名（统一管理于 web_infra.infra.constants）
TRACE_ID_HEADER = AUTH_HEADER_TRACE_ID

# uvicorn 访问日志 logger 名（由本中间件接管，关闭原生输出）
_UVICORN_ACCESS_LOGGER_NAME = "uvicorn.access"

# app.state 标记：标记应用已装配本中间件（Application 生命周期据此接管 uvicorn.access）
_MIDDLEWARE_STATE_MARK = "_web_infra_logging_middleware"

# 路径归一化：UUID/数字 ID 段替换为 {id}，避免指标标签携带高基数动态值（§18.1）
_PATH_ID_SEGMENT_RE = re.compile(r"/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|/\d+")

# 慢请求样本参数摘要最大长度（防超长参数撑爆内存/日志）
_PARAM_SUMMARY_MAX_LEN = 500


def disable_uvicorn_access_log() -> None:
    """关闭 uvicorn 原生访问日志，由本中间件输出唯一访问日志。

    uvicorn 在 Config 初始化时默认给 uvicorn.access 挂载 AccessFormatter handler（access_log=True），
    协议层以 hasHandlers() 判定是否在响应完成后输出原生访问日志——该日志的 IP 为直连方
    （容器场景下是 OpenResty/网关容器 IP），非真实客户端 IP。
    此处移除 uvicorn.access 的 handler 并禁止向上传播（等价 uvicorn access_log=False），
    使 hasHandlers() 恒为 False、原生访问日志不再输出；本中间件经 web_infra.<service>.access
    输出的访问日志仍走框架根日志器（文本/JSON 格式 + 敏感信息脱敏）。

    幂等可重复调用；需在 uvicorn 完成日志配置（Config 初始化）之后、接受连接之前执行，
    由中间件启动事件与 Application 生命周期保证（见 setup_uvicorn_access_log）。
    """
    uvicorn_access = logging.getLogger(_UVICORN_ACCESS_LOGGER_NAME)
    uvicorn_access.handlers = []
    uvicorn_access.propagate = False


def setup_uvicorn_access_log(app: FastAPI) -> None:
    """应用启动阶段接管 uvicorn.access（供 Application 生命周期调用）。

    仅当应用装配了 LoggingMiddleware（app.state 标记）时关闭 uvicorn 原生访问日志，
    未装配时不干预，避免静默丢失原生访问日志。

    :param app: 当前应用实例
    """
    if getattr(app.state, _MIDDLEWARE_STATE_MARK, False):
        disable_uvicorn_access_log()


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


def _build_access_message(
    *,
    request: Request,
    trace_id: str,
    status_code: int,
    duration_ms: float,
    user_id: str | None,
    phase_timer: PhaseTimer,
) -> str:
    """构造访问日志消息：uvicorn 原生格式（客户端 IP:端口 - "方法 路径 HTTP/版本" 状态码）+ 框架扩展字段。

    路径携带 query 时一并输出（与 uvicorn 原生访问日志一致，get_path_with_query_string）；
    消息整体经 mask 脱敏（query 中的手机号/密钥等不落明文，规范 §17.3），根日志器的
    SensitiveDataFilter 会再次脱敏，双保险。

    :param request: 当前请求（scope["client"] 已由 apply_real_client_ip 改写为真实客户端 IP）
    :param trace_id: 链路 TraceId
    :param status_code: 响应状态码
    :param duration_ms: 请求总耗时（毫秒）
    :param user_id: 当前用户 ID（未登录为 None）
    :param phase_timer: 分阶段耗时器（mark_total 后）
    :return: 脱敏后的访问日志消息
    """
    client_addr = f"{request.client[0]}:{request.client[1]}" if request.client else "-"
    full_path = request.url.path
    if request.url.query:
        full_path = f"{full_path}?{request.url.query}"
    phase_fields = " ".join(f"{k}={v}" for k, v in phase_timer.to_log_fields().items())
    message = (
        f'{client_addr} - "{request.method} {full_path} HTTP/{request.scope.get("http_version", "1.1")}" {status_code}'
        f" trace_id={trace_id} duration_ms={duration_ms:.3f} user_id={user_id} {phase_fields}"
    )
    return mask(message)


class LoggingMiddleware(BaseHTTPMiddleware):
    """FastAPI 访问日志中间件（uvicorn 标准格式 + 真实客户端 IP）"""

    def __init__(self, app: ASGIApp, service_name: str = "app") -> None:
        super().__init__(app)
        self.logger = get_logger(f"{service_name}.access")
        self.service_name = service_name
        # 标记应用已装配本中间件：Application 生命周期据此在启动阶段关闭 uvicorn 原生访问日志
        if hasattr(app, "state"):
            setattr(app.state, _MIDDLEWARE_STATE_MARK, True)
        # 启动事件：默认 lifespan（普通 FastAPI 应用）在 uvicorn 完成日志配置后执行，
        # 早于任何连接建立，原生访问日志全程不输出（Application 自定义 lifespan 场景见
        # application.py 生命周期内调用 setup_uvicorn_access_log）
        if hasattr(app, "add_event_handler"):
            app.add_event_handler("startup", disable_uvicorn_access_log)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """处理请求生命周期：解析真实客户端 IP、注入 TraceId、记录唯一访问日志与 RED 指标"""
        trace_id = request.headers.get(TRACE_ID_HEADER, str(uuid.uuid4()))
        request.state.trace_id = trace_id
        RequestContext.set_trace_id(trace_id)
        phase_timer = PhaseTimer.start()

        # 兜底关闭 uvicorn 原生访问日志（覆盖未触发启动事件/生命周期的场景，幂等）
        disable_uvicorn_access_log()

        # 解析真实客户端 IP 并写回 scope["client"]（request.client / 下游业务代码读取一致）
        real_ip = get_client_ip(request)
        apply_real_client_ip(request, real_ip)

        start_time = time.perf_counter()
        method = request.method
        path = request.url.path
        metric_path = _PATH_ID_SEGMENT_RE.sub("/{id}", path)
        HTTP_REQUESTS_IN_FLIGHT.labels(service=self.service_name).inc()

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
                logging.ERROR
                if status_code >= HttpStatusConstant.HTTP_SERVER_ERROR_MIN
                else logging.WARNING
                if status_code >= HttpStatusConstant.HTTP_CLIENT_ERROR_MIN or duration_ms > SysConstant.SYS_SLOW_REQUEST_THRESHOLD_MS
                else logging.INFO
            )
            self.logger.log(
                log_level,
                _build_access_message(
                    request=request,
                    trace_id=trace_id,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    user_id=user_id,
                    phase_timer=phase_timer,
                ),
            )
            return response
        finally:
            HTTP_REQUESTS_IN_FLIGHT.labels(service=self.service_name).dec()
            PhaseTimer.clear()


def setup_logging_middleware(app: FastAPI, service_name: str = "app") -> None:
    """注册访问日志中间件"""
    app.add_middleware(LoggingMiddleware, service_name=service_name)
