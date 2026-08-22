"""
SPI 注册表基类

@Author: 花海
@Date: 2026/08/22 12:00
@Description: 统一 SPI 注册表基类（命名空间感知 + 内置默认保护 + 优先级 + 实例侧 + 运行时切换）。
              领域注册表（CacheBackendRegistry / DatabaseRegistry 等）继承本类即获得：
              命名空间隔离（framework / user）、框架默认实现受保护（同名覆盖默认拒绝）、
              同命名空间按优先级解析。保留 register(name, factory) 旧签名（追加 keyword-only
              overwrite / namespace / priority），对既有调用向后兼容，不引入平行体系。
              另扩展实例侧注册（register_instance / get_instance，满足实例引用与双实例隔离）、
              运行时动态切换（activate / deactivate，不重启更换实现）、统一解析入口 resolve
              （'ref:' 实例引用 / 工厂实例化)与策略组合器回退 fallback（主策略失效自动回退）。
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
        """按解析顺序返回工厂（含优先级与运行时切换），未命中返回 None。

        纯名命中 `_active` 切换表时改为按切换目标解析；显式 'ns:name' 绕过切换（保持可切换）。
        """
        if ":" not in name:
            target = cls._active_store().get(name)
            if target is not None:
                name = target
        return cls._resolve_plain(name)

    @classmethod
    def _resolve_plain(cls, name: str) -> SpiFactory | None:
        """按 'ns:name' 显式命名空间 > user > framework 的顺序返回工厂（含优先级）。"""
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

    # ------------------------------------------------------------------
    # 实例侧：满足实例引用（ref:）与双实例隔离——同名可在 framework / user 各自注册
    # 不同实例；代码共享、实例隔离（每子类独立 _instances）。
    # ------------------------------------------------------------------

    @classmethod
    def _inst_store(cls) -> dict[str, dict[str, Any]]:
        """每子类独立存储：首次访问时在子类上惰性创建 `_instances`，避免跨子类共享字典。

        结构同 `_store()`：`{namespace: {name: instance}}`，实例侧无优先级。
        """
        if "_instances" not in cls.__dict__:
            cls._instances = {}
        return cls._instances

    @classmethod
    def register_instance(
        cls,
        name: str,
        instance: Any,
        *,
        namespace: str | None = None,
        overwrite: bool = False,
    ) -> None:
        """登记 SPI 实例引用。

        与 register 同命名空间/同名规则：'ns:name' 限定命名空间；同名且未 overwrite 抛 ValueError。
        :param name: 实例名（'ns:name' 形式限定命名空间）
        :param instance: 实例对象（resolve 的 'ref:' 前缀直接返回，不调用工厂）
        :param namespace: 命名空间（None → DEFAULT_NAMESPACE='user'）
        :param overwrite: 已存在时是否覆盖
        :raises ValueError: 实例名为空 / 同名已存在且未显式覆盖
        """
        if not name:
            raise ValueError("SPI 实例名不能为空")
        ns = namespace or cls.DEFAULT_NAMESPACE
        if ":" in name and namespace is None:
            ns, name = name.split(":", 1)
        with cls._lock:
            ns_map = cls._inst_store().setdefault(ns, {})
            if name in ns_map and not overwrite:
                raise ValueError(
                    f"SPI 实例 '{ns}:{name}' 已存在（覆盖需 register_instance(..., overwrite=True)）"
                )
            ns_map[name] = instance

    @classmethod
    def get_instance(cls, name: str) -> Any:
        """解析实例引用；未命中抛 KeyError。

        解析顺序：'ns:name' 显式命名空间 > DEFAULT_NAMESPACE(user) > FRAMEWORK_NAMESPACE；
        纯名命中 `_active` 切换表时按切换目标解析，显式 'ns:name' 绕过切换。
        """
        with cls._lock:
            instance = cls._resolve_instance(name)
        if instance is None:
            raise KeyError(name)
        return instance

    @classmethod
    def _resolve_instance(cls, name: str) -> Any | None:
        """按解析顺序返回实例（含运行时切换），未命中返回 None。"""
        if ":" not in name:
            target = cls._active_store().get(name)
            if target is not None:
                name = target
        return cls._resolve_instance_plain(name)

    @classmethod
    def _resolve_instance_plain(cls, name: str) -> Any | None:
        """按 'ns:name' 显式命名空间 > user > framework 的顺序返回实例。"""
        if ":" in name:
            ns, plain = name.split(":", 1)
            return cls._inst_store().get(ns, {}).get(plain)
        for ns in (cls.DEFAULT_NAMESPACE, cls.FRAMEWORK_NAMESPACE):
            instance = cls._inst_store().get(ns, {}).get(name)
            if instance is not None:
                return instance
        return None

    @classmethod
    def unregister_instance(cls, name: str) -> None:
        """注销实例引用（不存在时静默）；'ns:name' 限定命名空间，否则跨命名空间移除。"""
        if ":" in name:
            ns, plain = name.split(":", 1)
            with cls._lock:
                cls._inst_store().get(ns, {}).pop(plain, None)
            return
        with cls._lock:
            for ns in (cls.DEFAULT_NAMESPACE, cls.FRAMEWORK_NAMESPACE):
                cls._inst_store().get(ns, {}).pop(name, None)

    @classmethod
    def registered_instance_names(cls) -> list[str]:
        """已注册实例名清单（跨命名空间去重，顺序 user→framework）。"""
        with cls._lock:
            seen: dict[str, None] = {}
            for ns in (cls.DEFAULT_NAMESPACE, cls.FRAMEWORK_NAMESPACE):
                for nm in cls._inst_store().get(ns, {}):
                    seen.setdefault(nm, None)
            return list(seen)

    @classmethod
    def registered_framework_instance_names(cls) -> list[str]:
        """框架命名空间已注册实例名清单。"""
        with cls._lock:
            return list(cls._inst_store().get(cls.FRAMEWORK_NAMESPACE, {}))

    # ------------------------------------------------------------------
    # 运行时动态切换：不重启即可更换实现（activate / deactivate / active_names），
    # 每子类独立 _active，仅影响纯名解析；显式 'ns:name' 绕过切换。
    # ------------------------------------------------------------------

    @classmethod
    def _active_store(cls) -> dict[str, str]:
        """每子类独立存储：首次访问时在子类上惰性创建 `_active`，避免跨子类共享字典。

        `_active`：`{name: target}`，target 为要切换到的解析目标（可为 'ns:name' 或纯 name）。
        """
        if "_active" not in cls.__dict__:
            cls._active = {}
        return cls._active

    @classmethod
    def activate(cls, name: str, target: str) -> None:
        """把 name 的解析切换到 target（不重启更换实现）。

        :param name: 要被切换的纯名（同名解析将被重定向）
        :param target: 切换目标（'ns:name' 或纯 name，如 activate("memory", "user:mymemory")）
        """
        if not name:
            raise ValueError("SPI 切换名不能为空")
        if not target:
            raise ValueError("SPI 切换目标不能为空")
        with cls._lock:
            cls._active_store()[name] = target

    @classmethod
    def deactivate(cls, name: str) -> None:
        """移除 name 的切换，恢复默认解析（不存在时静默）。"""
        with cls._lock:
            cls._active_store().pop(name, None)

    @classmethod
    def active_names(cls) -> list[str]:
        """当前处于切换态的名字清单。"""
        with cls._lock:
            return list(cls._active_store())

    # ------------------------------------------------------------------
    # 统一解析入口 resolve + 策略组合器回退 fallback
    # ------------------------------------------------------------------

    @classmethod
    def resolve(cls, name: str, *build_args, **build_kwargs) -> Any:
        """统一解析入口。

        :param name: 'ref:xxx' → 返回实例引用（get_instance，不调用工厂）；否则调用工厂实例化
        :param build_args / build_kwargs: 透传给工厂的实例化参数（'ref:' 分支忽略，亦可供纯查询空参）
        """
        if name.startswith("ref:"):
            return cls.get_instance(name[4:])
        return cls.get(name)(*build_args, **build_kwargs)

    @classmethod
    def fallback(cls, primary_name: str, fallback_name: str) -> SpiFactory:
        """策略组合器回退：返回组合工厂 `_combined(*args, **kwargs)`。

        先按 primary 解析并实例化；若抛 Exception，则回退按 fallback 解析并实例化。
        """
        def _combined(*args, **kwargs):
            try:
                return cls.get(primary_name)(*args, **kwargs)
            except Exception:
                return cls.get(fallback_name)(*args, **kwargs)

        return _combined
