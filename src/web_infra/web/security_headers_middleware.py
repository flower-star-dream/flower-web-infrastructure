"""
安全响应头中间件

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 注入安全响应头（整改 S25-1，规范 §25 安全加固）：
              Content-Security-Policy（默认宽松 default-src 'self'）、X-Content-Type-Options: nosniff、
              X-Frame-Options: DENY、Referrer-Policy: no-referrer；各项可配置，默认值收敛于
              config/application.default.yml（app.web.middlewares.security_headers），与类内默认保持一致。
              默认不引入（yml enabled: false），由业务配置显式启用，避免破坏既有响应头断言（向后兼容）。
"""
from __future__ import annotations

from typing import Final

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# 安全响应头默认值（与 application.default.yml 的 app.web.middlewares.security_headers 保持一致）
_DEFAULT_HEADERS: Final[dict[str, str]] = {
    "Content-Security-Policy": "default-src 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件：为所有响应注入安全头（已存在的同名响应头不覆盖）"""

    def __init__(
        self,
        app: FastAPI,
        content_security_policy: str | None = None,
        x_content_type_options: str | None = None,
        x_frame_options: str | None = None,
        referrer_policy: str | None = None,
    ) -> None:
        """初始化安全响应头中间件。

        :param app: FastAPI 应用实例
        :param content_security_policy: CSP 策略（默认 "default-src 'self'"）
        :param x_content_type_options: X-Content-Type-Options（默认 "nosniff"）
        :param x_frame_options: X-Frame-Options（默认 "DENY"）
        :param referrer_policy: Referrer-Policy（默认 "no-referrer"）
        """
        super().__init__(app)
        self._headers: dict[str, str] = {
            "Content-Security-Policy": content_security_policy or _DEFAULT_HEADERS["Content-Security-Policy"],
            "X-Content-Type-Options": x_content_type_options or _DEFAULT_HEADERS["X-Content-Type-Options"],
            "X-Frame-Options": x_frame_options or _DEFAULT_HEADERS["X-Frame-Options"],
            "Referrer-Policy": referrer_policy or _DEFAULT_HEADERS["Referrer-Policy"],
        }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """注入安全响应头（不覆盖业务已设置的同名头）"""
        response = await call_next(request)
        for name, value in self._headers.items():
            response.headers.setdefault(name, value)
        return response
