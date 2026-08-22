"""
AOP 切面注册表

@Author: 花海
@Date: 2026/08/22 14:00
@Description: AOP 切面注册表（类级注册，全局装配，同 CacheBackendRegistry 风格）。
              AspectRegistry.matching(pointcut, target) 返回命中切面并排序：
              order 升序（从小到大由外及里）；同 order 按注册序兜底（跨进程稳定）。
              供 AspectWeaver 织入时按命中切面链构建嵌套包装。
"""
from __future__ import annotations

from threading import Lock
from typing import ClassVar

from web_infra.core.aop.aspect import Aspect
from web_infra.core.aop.pointcut import Pointcut


class AspectRegistry:
    """AOP 切面注册表（类级注册，全局装配；类级锁保护并发 register）"""

    _aspects: ClassVar[dict[str, Aspect]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, aspect: Aspect, overwrite: bool = False) -> None:
        """登记切面（同名默认拒绝；overwrite=True 才覆盖）。

        :param aspect: 切面对象
        :param overwrite: 同名已存在时是否显式覆盖
        :raises ValueError: 切面名为空
        """
        if not aspect.name:
            raise ValueError("切面名不能为空")
        with cls._lock:
            existing = cls._aspects.get(aspect.name)
            if existing is not None and not overwrite:
                raise ValueError(f"切面 {aspect.name} 已注册（覆盖需 register(..., overwrite=True)）")
            cls._aspects[aspect.name] = aspect

    @classmethod
    def get(cls, name: str) -> Aspect | None:
        """按切面名查询（未注册返回 None）。

        :param name: 切面名
        """
        return cls._aspects.get(name)

    @classmethod
    def names(cls) -> list[str]:
        """已登记切面名清单（按注册顺序）"""
        return list(cls._aspects)

    @classmethod
    def matching(cls, pointcut: Pointcut, target: str, args: tuple = ()) -> list[Aspect]:
        """返回命中切点且排序后的切面链：order 升序由外及里；同 order 按注册序兜底。

        :param pointcut: 待匹配切点
        :param target: 目标完整名（module.Class.method）
        :param args: 目标位置参数（用于参数类型匹配）
        """
        hit = [
            aspect
            for aspect in cls._aspects.values()
            if aspect.pointcut.matches(target) and aspect.pointcut.matches_args(args)
        ]
        order = {aspect.name: i for i, aspect in enumerate(cls._aspects.values())}
        hit.sort(key=lambda a: (a.order, order[a.name]))
        return hit


def _clear() -> None:
    """清空注册表（测试专用）"""
    with AspectRegistry._lock:
        AspectRegistry._aspects.clear()
