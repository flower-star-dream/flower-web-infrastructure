"""
HTTP 状态码常量（HTTP_ 前缀）

@Author: 花海
@Date: 2026/08/16
@Description: HTTP 状态码统一常量（规范 §5.3 常量分类统一管理）：
              值复用 starlette.status（已有库标准常量，避免自定义数字），
              框架与脚手架统一从本类引用，禁止在业务代码散落状态码字面量（防止冲突/重复定义）。
              区间下限常量（HTTP_CLIENT_ERROR_MIN / HTTP_SERVER_ERROR_MIN）供 >= 区间判断使用。
"""
from __future__ import annotations

from starlette import status


class HttpStatusConstant:
    """HTTP 状态码常量类（值以 starlette.status 为标准，规范 §5.3）"""

    # 2xx 成功
    HTTP_OK = status.HTTP_200_OK
    HTTP_CREATED = status.HTTP_201_CREATED
    HTTP_ACCEPTED = status.HTTP_202_ACCEPTED
    HTTP_NO_CONTENT = status.HTTP_204_NO_CONTENT

    # 4xx 客户端错误
    HTTP_BAD_REQUEST = status.HTTP_400_BAD_REQUEST
    HTTP_UNAUTHORIZED = status.HTTP_401_UNAUTHORIZED
    HTTP_FORBIDDEN = status.HTTP_403_FORBIDDEN
    HTTP_NOT_FOUND = status.HTTP_404_NOT_FOUND
    HTTP_METHOD_NOT_ALLOWED = status.HTTP_405_METHOD_NOT_ALLOWED
    HTTP_CONFLICT = status.HTTP_409_CONFLICT
    # starlette 1.x 常量名为 HTTP_422_UNPROCESSABLE_CONTENT；低版本名为 HTTP_422_UNPROCESSABLE_ENTITY（访问会触发弃用警告），
    # 故 fallback 用标准字面量 422 兜底，避免兼容写法触发 deprecation warning
    HTTP_UNPROCESSABLE_ENTITY = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
    HTTP_LOCKED = status.HTTP_423_LOCKED
    HTTP_TOO_MANY_REQUESTS = status.HTTP_429_TOO_MANY_REQUESTS

    # 5xx 服务端错误
    HTTP_INTERNAL_SERVER_ERROR = status.HTTP_500_INTERNAL_SERVER_ERROR
    HTTP_SERVICE_UNAVAILABLE = status.HTTP_503_SERVICE_UNAVAILABLE

    # 区间下限（>= 区间判断用；starlette 无区间常量，值取对应大类首码，语义见注释）
    HTTP_CLIENT_ERROR_MIN = status.HTTP_400_BAD_REQUEST          # 4xx 区间下限（客户端错误）
    HTTP_SERVER_ERROR_MIN = status.HTTP_500_INTERNAL_SERVER_ERROR  # 5xx 区间下限（服务端错误）
