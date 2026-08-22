"""
应用事件基类

@Author: 花海
@Date: 2026/08/22 17:00
@Description: 应用事件（对标 Spring ApplicationEvent）：进程内发布/订阅的事件载体。
              子类声明 event_name（默认取类名小写下划线）；payload 携带业务数据；
              trace_id 在发布时自动绑定请求上下文，随事件透传。区别于 MQ（跨服务），
              本事件用于同服务内解耦。
"""
from __future__ import annotations

import re
import time
from typing import Any, ClassVar

from web_infra.infra.context import RequestContext


def _default_event_name(cls_name: str) -> str:
    """类名 -> 默认事件名（CamelCase -> snake_case）"""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", cls_name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class ApplicationEvent:
    """应用事件基类。

    :param payload: 事件携带的业务数据
    :param trace_id: 链路 ID（缺省取自 RequestContext，避免手动传）
    :param published_at: 发布时间（perf_counter，内置）
    """

    event_name: ClassVar[str] = ""  # 子类覆盖；缺省由类名推导

    def __init__(self, payload: Any = None, *, trace_id: str | None = None) -> None:
        self.payload = payload
        self.trace_id = trace_id or RequestContext.get_trace_id() or ""
        self.published_at = time.perf_counter()  # 事件创建时刻（monotonic，供排序/审计）

    @classmethod
    def resolve_event_name(cls) -> str:
        """解析事件名：显式声明优先，否则由类名推导。"""
        return cls.event_name or _default_event_name(cls.__name__)


class ApplicationStartingEvent(ApplicationEvent):
    """应用启动事件类

    @Author: 花海
    @Date: 2026/08/22 17:30
    @Description: 框架启动阶段最前发布（清理上下文/uvicorn 访问日志之后、扩展 startup 之前），
                  供监听器在业务扩展点启动前感知应用开始启动。payload 透传（如 settings/app）。
    """

    event_name = "application_starting"


class ApplicationReadyEvent(ApplicationEvent):
    """应用就绪事件类

    @Author: 花海
    @Date: 2026/08/22 17:30
    @Description: 全部启动完成（容量采样启动后、yield 接受请求前）发布，表示应用已就绪可对外服务。
                  供监听器做就绪后的初始化/预热。payload 透传（如 settings/app）。
    """

    event_name = "application_ready"


class ApplicationStoppingEvent(ApplicationEvent):
    """应用停机中事件类

    @Author: 花海
    @Date: 2026/08/22 17:30
    @Description: yield 恢复后（收到停机信号）、开始释放资源前发布。供监听器在资源释放前做收尾。
                  payload 透传（如 settings/app）。
    """

    event_name = "application_stopping"


class ApplicationStoppedEvent(ApplicationEvent):
    """应用已停机事件类

    @Author: 花海
    @Date: 2026/08/22 17:30
    @Description: _shutdown() 完成后（最末尾）发布，表示应用已完全停机。供监听器做最终清理/审计。
                  payload 透传（如 settings/app）。
    """

    event_name = "application_stopped"


class HttpRequestStartedEvent(ApplicationEvent):
    """HTTP 请求开始事件类

    @Author: 花海
    @Date: 2026/08/22 18:00
    @Description: 请求处理开始时发布（解析真实客户端 IP 与 TraceId 后、call_next 调用前）。
                  payload 透传（含 trace_id/method/path/query/client_ip），供监听器感知请求进入。
    """

    event_name = "http_request_started"


class HttpRequestCompletedEvent(ApplicationEvent):
    """HTTP 请求完成事件类

    @Author: 花海
    @Date: 2026/08/22 18:00
    @Description: 请求处理结束（成功或异常）时在 finally 统一发布，携带耗时/状态码/是否出错。
                  payload 透传（含 trace_id/method/path/status_code/duration_ms/is_error）。
    """

    event_name = "http_request_completed"


class AuthTokenIssuedEvent(ApplicationEvent):
    """认证 Token 签发事件类

    @Author: 花海
    @Date: 2026/08/22 20:00
    @Description: JWT 签发成功时发布（JWTUtil.generate_token），payload 携带 user_id/username/jti/login_type，
                  供监听器感知新凭证签发（如审计、设备凭证复用统计）。
    """

    event_name = "auth_token_issued"


class AuthTokenRevokedEvent(ApplicationEvent):
    """认证 Token 撤销事件类

    @Author: 花海
    @Date: 2026/08/22 20:00
    @Description: 指定 token 登出/撤销成功时发布（JWTUtil.invalidate_token 的 revoke 返回 True），
                  payload 携带 user_id/jti，供监听器感知凭证失效（如审计、下线通知）。
    """

    event_name = "auth_token_revoked"


class AuthLoginSuccessEvent(ApplicationEvent):
    """三方登录成功事件类

    @Author: 花海
    @Date: 2026/08/22 20:00
    @Description: 三方登录绑定成功并签发自有 JWT 后发布（SocialLoginService.login 的已绑定分支），
                  payload 携带 provider/user_id/openid，供监听器感知用户登录成功（如登录流水、风控）。
    """

    event_name = "auth_login_success"


class AuthLoginFailedEvent(ApplicationEvent):
    """三方登录失败事件类

    @Author: 花海
    @Date: 2026/08/22 20:00
    @Description: 三方登录整体抛异常时发布（SocialLoginService.login 的 try/except），
                  payload 携带 provider/reason，供监听器感知登录失败（如风控、告警统计）。
    """

    event_name = "auth_login_failed"
