"""
全局异常处理

@Author: 花海
@Date: 2026/08/14 10:00
@Description: FastAPI 全局异常处理器，将各类异常统一映射为 Result 响应结构（规范 §4.7）。
              - WebInfraException -> 原样透传错误码
              - 请求参数校验异常 -> E1-PARAM-000（HTTP 400）
              - 未捕获异常 -> E5-SYS-000（HTTP 500）
              服务端日志记录完整错误码，边界收敛仅作用于出网响应体。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from web_infra.error.common_error_code import CommonErrorCode
from web_infra.error.error_code import converge_error_code
from web_infra.error.web_infra_exception import WebInfraException
from web_infra.result import Result

logger = logging.getLogger("web_infra")


def _json_response(code: str, message: str, http_status: int, data: object = None) -> JSONResponse:
    """构造统一响应结构 JSON 响应（HTTP 状态码原样透传，见规范 §4.6）"""
    return JSONResponse(
        status_code=http_status,
        content=Result.failure(code=code, message=message, data=data).model_dump(),
    )


def _converged_response(code: str, message: str, http_status: int, data: object = None) -> JSONResponse:
    """出网响应：E3/E5 收敛为大类前缀码 + 大类默认文案，其余透传（规范 §4.6.1 边界收敛）"""
    conv_code, conv_message = converge_error_code(code, message)
    return _json_response(conv_code, conv_message, http_status, data)


def register_global_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器到 FastAPI 应用"""

    @app.exception_handler(WebInfraException)
    async def handle_web_infra_exception(request: Request, exc: WebInfraException) -> JSONResponse:
        # 服务端日志记录完整错误码（规范 §4.6.1 日志约束）
        logger.log(
            exc.error_code.log_level,
            "业务异常 | code=%s | message=%s",
            exc.code,
            exc.message,
        )
        # 出网响应执行边界收敛（E3/E5 隐藏子类与编号，规范 §4.6.1）
        return _converged_response(exc.code, exc.message, exc.http_status, exc.data)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 参数校验失败统一映射为 E1-PARAM-000（规范 §4.2：E1 -> 400）
        logger.info("参数校验失败 | %s", exc.errors())
        return _converged_response(
            CommonErrorCode.PARAM_INVALID.code,
            CommonErrorCode.PARAM_INVALID.message,
            CommonErrorCode.PARAM_INVALID.http_status,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Starlette 抛出的 HTTP 异常（如 404/405）转统一结构
        code = CommonErrorCode.SYS_INTERNAL.code
        if exc.status_code == 404:
            code = CommonErrorCode.COMMON_NOT_FOUND.code
        elif exc.status_code == 405:
            code = CommonErrorCode.HTTP_METHOD_NOT_ALLOWED.code
        return _converged_response(code, exc.detail or "", exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        # 兜底：未知异常映射 E5-SYS-000（规范 §4.1 安全失败原则）
        logger.exception("未捕获异常")
        code = CommonErrorCode.SYS_UNKNOWN
        return _converged_response(code.code, code.message, code.http_status)
