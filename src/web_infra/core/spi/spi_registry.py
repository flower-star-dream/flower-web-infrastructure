"""
SPI 注册表基类

@Author: 花海
@Date: 2026/08/22 12:00
@Description: 统一 SPI 注册表基类（命名空间感知 + 内置默认保护 + 优先级）。
              领域注册表（CacheBackendRegistry / DatabaseRegistry 等）继承本类即获得：
              命名空间隔离（framework / user）、框架默认实现受保护（同名覆盖默认拒绝）、
              同命名空间按优先级解析。保留 register(name, factory) 旧签名（追加 keyword-only
              overwrite / namespace / priority），对既有调用向后兼容，不引入平行体系。
"""
from __future__ import annotations

from threading import Lock
from typing import Any, Callable

#: SPI 实现工厂签名（入参由各领域注册表 create / _resolve_registry 决定）
SpiFactory = Callable[..., Any]


class SpiRegistry:
    """统一 SPI 注册表基类（类级注册，全局装配）。"""

    _lock = Lock()

    DEFAULT_NAMESPACE = "user"        # 业务自定义实现默认命名空间
    FRAMEWORK_NAMESPACE = "framework"  # 框架内置默认实现命名空间（受保护）

    @classmethod
    def _store(cls) -> dict[str, dict[str, tuple[int, SpiFactory]]]:
        """每子类独立存储：首次访问时在子类上惰性创建 `_namespaces`，避免跨注册表共享同一字典。

        不同领域注册表（CacheBackendRegistry / DatabaseRegistry 等）各自持有一份命名空间字典，
        互不串扰（对齐既有各注册表各自持有 `_factories` ClassVar 的隔离约定）。
        """
        if "_namespaces" not in cls.__dict__:
            cls._namespaces = {}
        return cls._namespaces

    @classmethod
    def register(
        cls,
        name: str,
        factory: SpiFactory,
        *,
        namespace: str | None = None,
        priority: int = 0,
        overwrite: bool = False,
    ) -> None:
        """登记 SPI 实现。

        :param name: 实现名（与 yml app.*.type 匹配；'ns:name' 形式限定命名空间）
        :param factory: 实现工厂（入参由各领域注册表 create 决定）
        :param namespace: 命名空间（None → DEFAULT_NAMESPACE='user'）
        :param priority: 同命名空间内优先级（越大越先被 get 命中）
        :param overwrite: 已存在时是否覆盖（框架命名空间默认需显式 True 才可覆盖）
        :raises ValueError: 实现名为空 / 同名已存在且未显式覆盖
        """
        if not name:
            raise ValueError("SPI 实现名不能为空")
        ns = namespace or cls.DEFAULT_NAMESPACE
        if ":" in name and namespace is None:
            ns, name = name.split(":", 1)
        with cls._lock:
            ns_map = cls._store().setdefault(ns, {})
            existing = ns_map.get(name)
            if existing is not None and not overwrite:
                raise ValueError(
                    f"SPI 实现 '{ns}:{name}' 已存在（覆盖需 register(..., overwrite=True)）"
                )
            ns_map[name] = (priority, factory)

    @classmethod
    def get(cls, name: str) -> SpiFactory:
        """解析实现工厂；未注册抛 KeyError（装配期由 _resolve_registry 转 ConfigError）。

        解析顺序：'ns:name' 显式命名空间 > DEFAULT_NAMESPACE(user) > FRAMEWORK_NAMESPACE；
        同命名空间内取优先级最高者。
        """
        with cls._lock:
            factory = cls._resolve(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def _resolve(cls, name: str) -> SpiFactory | None:
        """按解析顺序返回工厂（含优先级），未命中返回 None。"""
        if ":" in name:
            ns, plain = name.split(":", 1)
            entry = cls._store().get(ns, {}).get(plain)
            return entry[1] if entry else None
        for ns in (cls.DEFAULT_NAMESPACE, cls.FRAMEWORK_NAMESPACE):
            entry = cls._store().get(ns, {}).get(name)
            if entry is not None:
                return entry[1]
        return None

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销实现（不存在时静默）；'ns:name' 限定命名空间，否则跨命名空间移除。"""
        if ":" in name:
            ns, plain = name.split(":", 1)
            with cls._lock:
                cls._store().get(ns, {}).pop(plain, None)
            return
        with cls._lock:
            for ns in (cls.DEFAULT_NAMESPACE, cls.FRAMEWORK_NAMESPACE):
                cls._store().get(ns, {}).pop(name, None)

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册实现名清单（跨命名空间去重，顺序 user→framework，供错误提示）。"""
        with cls._lock:
            seen: dict[str, None] = {}
            for ns in (cls.DEFAULT_NAMESPACE, cls.FRAMEWORK_NAMESPACE):
                for nm in cls._store().get(ns, {}):
                    seen.setdefault(nm, None)
            return list(seen)

    @classmethod
    def registered_framework_names(cls) -> list[str]:
        """框架命名空间已注册实现名清单（启动完整性校验用）。"""
        with cls._lock:
            return list(cls._store().get(cls.FRAMEWORK_NAMESPACE, {}))

    @classmethod
    def registered_namespaces(cls) -> list[str]:
        """已注册命名空间清单。"""
        with cls._lock:
            return list(cls._store())
