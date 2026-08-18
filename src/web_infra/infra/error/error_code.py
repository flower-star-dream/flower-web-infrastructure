"""
错误码定义

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 错误码定义、解析入口与边界收敛，遵循规范 §4。
              错误码格式 E<大类>-<子类/域>-<3位编号>，成功码 S0000。
              统一入口对外将 E3/E5 收敛为大类前缀码（隐藏子类与编号），
              服务端日志始终保留完整错误码。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from web_infra.infra.error.biz_exception import BizException

# ---------------------------------------------------------------------------
# 大类（Category）元数据：HTTP 状态码 / 日志级别 / 是否可重试
# ---------------------------------------------------------------------------

# 大类 -> 默认 HTTP 状态码（规范 §4.2 错误码分类表）
_CATEGORY_HTTP_STATUS: dict[str, int] = {
    "E1": 400,
    "E2": 401,
    "E3": 500,
    "E4": 422,
    "E5": 500,
    "S": 200,
}

# 大类 -> 日志级别（客户端错误 INFO，服务端错误 ERROR，业务域 WARN）
_CATEGORY_LOG_LEVEL: dict[str, int] = {
    "E1": logging.INFO,
    "E2": logging.INFO,
    "E3": logging.ERROR,
    "E4": logging.WARNING,
    "E5": logging.ERROR,
    "S": logging.INFO,
}

# 仅 E3 基础设施类可重试（规范 §4.2）
_RETRYABLE_CATEGORIES: frozenset[str] = frozenset({"E3"})

# E3/E5 对外收敛后的大类默认文案（规范 §4.6.1）
CONVERGED_MESSAGES: dict[str, str] = {
    "E3": "服务暂时不可用，请稍后重试",
    "E5": "系统繁忙，请稍后重试",
}

# 需要透传的大类（规范 §4.6.1）
PASS_CATEGORIES: frozenset[str] = frozenset({"E1", "E2", "E4", "S"})
# 需要收敛隐藏的大类
HIDE_CATEGORIES: frozenset[str] = frozenset({"E3", "E5"})


@dataclass(frozen=True)
class ErrorCode:
    """错误码定义（code + message + HTTP 状态 + 大类 + 可重试 + 日志级别）"""

    code: str
    message: str
    http_status: int
    category: str
    retryable: bool = False
    log_level: int = logging.INFO

    def to_exception(self, message: str | None = None, data: Any = None) -> "BizException":
        """将错误码转为业务异常（统一异常抛出约定：`raise 错误码.to_exception(message=...)`）。

        业务代码统一经错误码抛出业务异常，避免散落 BizException 构造（与框架内部一致）；
        域专属异常（参数 ParamException / 权限 PermException / 认证 AuthException）仍用对应构造函数。
        未传 message 时回落错误码默认文案，data 透传给异常实例（全局异常处理器输出）。

        :param message: 业务提示文案（缺省用错误码默认文案）
        :param data: 附加数据（随异常透传至统一响应 data 字段）
        :return: 携带本错误码的 BizException 实例
        """
        from web_infra.infra.error.biz_exception import BizException

        return BizException(self, message=message, data=data)


def parse_category(code: str) -> str:
    """解析错误码大类（S0000 -> S；未知前缀安全兜底为 E5，见规范 §4.1）"""
    if code == "S0000":
        return "S"
    if not code or not code.startswith("E"):
        return "E5"
    prefix = code.split("-", 1)[0]
    return prefix if prefix in {"E1", "E2", "E3", "E4", "E5"} else "E5"


def derive_http_status(code: str) -> int:
    """按大类推导 HTTP 状态码，子类按语义覆盖（E2-PERM->403，E3-LOCK->423，见规范 §4.2）"""
    if code.startswith("E2-PERM"):
        return 403
    if code.startswith("E3-LOCK"):
        return 423
    return _CATEGORY_HTTP_STATUS.get(parse_category(code), 500)


def derive_log_level(category: str) -> int:
    """按大类推导日志级别"""
    return _CATEGORY_LOG_LEVEL.get(category, logging.ERROR)


def is_client_error(category: str) -> bool:
    """是否为客户端错误（客户端错误记 INFO，服务端错误记 ERROR，见规范 §4.3）"""
    return category in {"E1", "E2", "E4"}


def is_retryable(category: str) -> bool:
    """是否可重试（仅 E3 基础设施类可重试）"""
    return category in _RETRYABLE_CATEGORIES


def converge_error_code(code: str, message: str | None = None) -> tuple[str, str]:
    """边界收敛：E3/E5 收敛为大类前缀码 + 大类默认文案，其余透传（规范 §4.6.1）"""
    category = parse_category(code)
    if category in HIDE_CATEGORIES:
        return category, CONVERGED_MESSAGES[category]
    return code, message or ""
