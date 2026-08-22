"""
切点匹配规则

@Author: 花海
@Date: 2026/08/22 14:00
@Description: AOP 切点定义（对标 Spring PointcutExpression）：按目标方法所属模块/类/方法名的
              正则表达式与参数类型匹配。切面注册时经 matches 判断是否命中目标方法；
              与具体实现无关（纯匹配规则），供 Aspect / AspectRegistry 复用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Pointcut:
    """切点匹配规则。

    :param module: 目标所属模块名正则（如 "service\\.order"；None 不限制）
    :param class_: 目标所属类名正则（如 "OrderService"；None 不限制）
    :param method: 目标方法名正则（如 "create_.*"；None 不限制）
    :param arg_types: 目标第一个参数的类型名（如 ("_Model",)；空元组不限制）
    """

    module: str | None = None
    class_: str | None = None
    method: str | None = None
    arg_types: tuple[str, ...] = ()

    def matches(self, target: str) -> bool:
        """是否命中目标（按 "module.Class.method" 拆解匹配）。

        :param target: 目标完整名（如 "service.order.OrderService.create_order"）
        """
        parts = target.rsplit(".", 2)
        method = parts[-1]
        class_name = parts[-2] if len(parts) >= 2 else None
        module = ".".join(parts[:-2]) if len(parts) >= 3 else None
        # 目标含类/方法层级（Class.method / module.Class.method）时才校验方法名正则；
        # 裸类名（如 "_Model"）不含方法信息，跳过 method 校验，避免对无方法目标的误判。
        if self.method and len(parts) >= 2 and not self.matches_method(method):
            return False
        if self.class_ and (class_name is None or not re.search(self.class_, class_name)):
            return False
        if self.module and (module is None or not re.search(self.module, module)):
            return False
        return True

    def matches_method(self, method: str) -> bool:
        """是否命中方法名（供测试/组装接口单独使用）。

        :param method: 方法名
        """
        if self.method is None:
            return True
        return re.search(self.method, method) is not None

    def matches_args(self, args: tuple) -> bool:
        """是否命中参数类型（按位置取第一个参数的类型名匹配）。

        :param args: 方法位置参数元组
        """
        if not self.arg_types:
            return True
        if not args:
            return False
        return type(args[0]).__name__ in self.arg_types
