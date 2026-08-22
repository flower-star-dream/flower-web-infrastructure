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
