"""
请求上下文

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 基于 contextvars 的请求上下文管理器，承载 TraceId、用户/租户/客户端等链路信息，
              遵循规范 §6.5（上下文传递）与 §17.4（链路追踪）。
              contextvars 自动随 asyncio 任务传递；跨线程（线程池）需显式 snapshot/restore。
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from typing import Any

from web_infra.infra.constants import AUTH_HEADER_TRACE_ID
from web_infra.infra.constants.sys_constant import SysConstant
from web_infra.infra.context.request_context_snapshot import RequestContextSnapshot

# 上下文变量（默认值为空字符串，表示"无上下文"）
_TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="")
_USER_ID: ContextVar[str] = ContextVar("user_id", default="")
_SCOPE: ContextVar[str] = ContextVar("scope", default="")
_CLIENT_ID: ContextVar[str] = ContextVar("client_id", default="")
_SERVICE_ID: ContextVar[str] = ContextVar("service_id", default="")
_TENANT_ID: ContextVar[str] = ContextVar("tenant_id", default="")

# 无用户上下文时的占位（统一管理于 SysConstant，见规范 §17.2）
ANONYMOUS_USER = SysConstant.SYS_ANONYMOUS_USER
SYSTEM_USER = SysConstant.SYS_SYSTEM_USER


def generate_trace_id() -> str:
    """生成一次请求链路唯一标识 TraceId（UUID4 十六进制）"""
    return uuid.uuid4().hex


class RequestContext:
    """请求上下文管理器：set/get/reset 各上下文字段，支持快照与恢复"""

    @staticmethod
    def set_trace_id(trace_id: str) -> Token:
        """设置 TraceId，返回用于恢复的 Token"""
        return _TRACE_ID.set(trace_id)

    @staticmethod
    def get_trace_id() -> str:
        """获取当前 TraceId"""
        return _TRACE_ID.get()

    @staticmethod
    def set_user_id(user_id: str) -> Token:
        """设置用户标识"""
        return _USER_ID.set(user_id)

    @staticmethod
    def get_user_id() -> str:
        """获取当前用户标识（无上下文时返回 anonymous 占位）"""
        value = _USER_ID.get()
        return value or ANONYMOUS_USER

    @staticmethod
    def set_scope(scope: str) -> Token:
        """设置权限范围"""
        return _SCOPE.set(scope)

    @staticmethod
    def get_scope() -> str:
        """获取权限范围"""
        return _SCOPE.get()

    @staticmethod
    def set_client_id(client_id: str) -> Token:
        """设置客户端标识（设备类型）"""
        return _CLIENT_ID.set(client_id)

    @staticmethod
    def get_client_id() -> str:
        """获取客户端标识"""
        return _CLIENT_ID.get()

    @staticmethod
    def set_service_id(service_id: str) -> Token:
        """设置服务标识（服务内部调用链路）"""
        return _SERVICE_ID.set(service_id)

    @staticmethod
    def get_service_id() -> str:
        """获取服务标识"""
        return _SERVICE_ID.get()

    @staticmethod
    def set_tenant_id(tenant_id: str) -> Token:
        """设置租户标识（多租户场景）"""
        return _TENANT_ID.set(tenant_id)

    @staticmethod
    def get_tenant_id() -> str:
        """获取租户标识"""
        return _TENANT_ID.get()

    @staticmethod
    def snapshot() -> RequestContextSnapshot:
        """快照当前上下文，用于异步/跨线程任务提交时携带（规范 §17.4）"""
        return RequestContextSnapshot(
            trace_id=_TRACE_ID.get(),
            user_id=_USER_ID.get(),
            scope=_SCOPE.get(),
            client_id=_CLIENT_ID.get(),
            service_id=_SERVICE_ID.get(),
            tenant_id=_TENANT_ID.get(),
        )

    @staticmethod
    def restore(snapshot: RequestContextSnapshot) -> None:
        """将快照恢复到当前上下文（在异步/子线程入口调用）"""
        _TRACE_ID.set(snapshot.trace_id)
        _USER_ID.set(snapshot.user_id)
        _SCOPE.set(snapshot.scope)
        _CLIENT_ID.set(snapshot.client_id)
        _SERVICE_ID.set(snapshot.service_id)
        _TENANT_ID.set(snapshot.tenant_id)

    @staticmethod
    def clear() -> None:
        """清理全部上下文（请求结束时调用，防止上下文泄漏）"""
        for var in (_TRACE_ID, _USER_ID, _SCOPE, _CLIENT_ID, _SERVICE_ID, _TENANT_ID):
            var.set("")

    @staticmethod
    def as_dict() -> dict[str, Any]:
        """以字典形式导出当前上下文（便于透传请求头/日志字段）"""
        return {
            AUTH_HEADER_TRACE_ID: _TRACE_ID.get(),
            "X-User-Id": _USER_ID.get(),
            "X-Scope": _SCOPE.get(),
            "X-Client-Id": _CLIENT_ID.get(),
            "X-Service-Id": _SERVICE_ID.get(),
            "X-Tenant-Id": _TENANT_ID.get(),
        }
