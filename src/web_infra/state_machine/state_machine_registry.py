"""
状态机注册表

@Author: 花海
@Date: 2026/08/16 16:00
@Description: 状态机注册表：按 (状态类, 事件类, 数据类) 注册与获取，引擎实例缓存。
              支持两种路由注册方式：@register 类装饰器（get 时无参惰性实例化）与
              register_instance 实例注册（构造注入场景）；构建期静态校验路由配置（P0）；
              支持 register_engine_factory 注册自定义引擎（SPI，可换第三方状态机库实现）。
              并发安全：注册表为进程内单例，注册/获取的 check-then-act 由类级 RLock 保护
              （构建为纯 CPU 微秒级操作，短暂阻塞事件循环可接受）；引擎 fire 为无状态操作不加锁。
"""
from __future__ import annotations

from threading import RLock
from typing import Callable, ClassVar, TypeVar, get_args, get_origin

from web_infra.state_machine.state_machine import StateMachine
from web_infra.state_machine.state_machine_engine import StateMachineEngine
from web_infra.state_machine.state_router import StateRouter

S = TypeVar("S")
E = TypeVar("E")
D = TypeVar("D")

_MachineKey = tuple[type, type, type]


class StateMachineRegistry:
    """状态机注册表：按 (状态类, 事件类, 数据类) 注册与获取；实例缓存，重复注册抛 ValueError"""

    _engines: ClassVar[dict[_MachineKey, StateMachineEngine]] = {}
    _router_classes: ClassVar[dict[_MachineKey, type]] = {}
    _engine_factories: ClassVar[dict[_MachineKey, Callable[[], StateMachineEngine]]] = {}
    # 类级锁：保护注册/获取的 check-then-act（并发首次 get 只构建一次、并发注册仅一个成功）
    _lock: ClassVar[RLock] = RLock()

    @classmethod
    def _resolve_generics(cls, router_cls: type) -> _MachineKey:
        """从 StateRouter[S, E, D] 泛型基类解析 (状态类, 事件类, 数据类)。

        :param router_cls: StateRouter 子类（须直接继承 StateRouter[S, E, D] 泛型基类）
        :raises TypeError: 未声明泛型或泛型参数数量不为 3
        """
        for base in getattr(router_cls, "__orig_bases__", ()):
            if get_origin(base) is StateRouter:
                args = get_args(base)
                if len(args) == 3:
                    return (args[0], args[1], args[2])
        raise TypeError(f"{router_cls.__name__} 未声明 StateRouter[状态, 事件, 数据] 泛型")

    @classmethod
    def _validate_router(cls, router: StateRouter) -> None:
        """构建期静态校验：组合表声明的事件均须在 dispatcher 注册处理器（P0 优化）。

        :param router: 路由实例
        :raises ValueError: 存在只声明无处理器的事件
        """
        config = router.get_state_event_target_config()
        dispatcher = router.get_event_dispatcher()
        declared_events = set()
        for event2target in config.values():
            declared_events.update(event2target.keys())
        missing = declared_events - set(dispatcher.keys())
        if missing:
            raise ValueError(
                f"状态机配置错误：组合表声明的事件 {sorted(missing, key=str)} "
                "未在 get_event_dispatcher 注册处理器"
            )

    @classmethod
    def register(cls, router_cls: type) -> type:
        """类装饰器：注册 StateRouter 子类，按泛型推导 key（实例与静态校验在 get 时执行）。

        :param router_cls: StateRouter 子类（需无参构造，或改用 register_instance）
        :return: 原类（可直接用作装饰器）
        :raises ValueError: 同 key 已注册
        """
        with cls._lock:
            key = cls._resolve_generics(router_cls)
            if key in cls._router_classes or key in cls._engines:
                raise ValueError(f"状态机已注册: {key}")
            cls._router_classes[key] = router_cls
        return router_cls

    @classmethod
    def register_instance(cls, router: StateRouter) -> StateRouter:
        """注册已装配的路由实例（业务路由需要构造注入时使用），立即执行静态校验。

        :param router: StateRouter 实例
        :return: 该实例
        :raises ValueError: 同 key 已注册 或 路由配置不合法
        """
        with cls._lock:
            key = cls._resolve_generics(type(router))
            if key in cls._engines or key in cls._router_classes:
                raise ValueError(f"状态机已注册: {key}")
            cls._validate_router(router)
            cls._engines[key] = StateMachine(router)
        return router

    @classmethod
    def register_engine_factory(
        cls,
        state_cls: type,
        event_cls: type,
        data_cls: type,
        factory: Callable[[], StateMachineEngine],
    ) -> None:
        """为指定 (状态类, 事件类, 数据类) 注册自定义引擎工厂（SPI 覆盖点）。

        默认引擎为自研 StateMachine；业务可基于第三方状态机库实现 StateMachineEngine
        后通过本方法替换，须在 get 之前调用。

        :param state_cls: 状态类（或状态值类型）
        :param event_cls: 事件类（或事件值类型）
        :param data_cls: 数据实体类
        :param factory: 无参引擎工厂（返回 StateMachineEngine 实例）
        :raises ValueError: 同 key 已存在引擎实例
        """
        with cls._lock:
            key = (state_cls, event_cls, data_cls)
            if key in cls._engines:
                raise ValueError(f"状态机引擎已存在: {key}")
            cls._engine_factories[key] = factory

    @classmethod
    def get(cls, state_cls: type, event_cls: type, data_cls: type) -> StateMachineEngine:
        """按 (状态类, 事件类, 数据类) 获取状态机引擎；未注册抛 KeyError。

        :param state_cls: 状态类（或状态值类型）
        :param event_cls: 事件类（或事件值类型）
        :param data_cls: 数据实体类
        :return: 状态机引擎实例（同 key 缓存复用；默认 StateMachine，可经 register_engine_factory 替换）
        :raises KeyError: 该 key 未注册
        """
        key = (state_cls, event_cls, data_cls)
        engine = cls._engines.get(key)
        if engine is None:
            # 双重检查锁定：快路径无锁读（GIL 保证单次读写原子），未命中才加锁构建，锁内二次确认
            with cls._lock:
                engine = cls._engines.get(key)
                if engine is None:
                    factory = cls._engine_factories.get(key)
                    if factory is not None:
                        engine = factory()
                    else:
                        router_cls = cls._router_classes.get(key)
                        if router_cls is None:
                            raise KeyError(f"未注册的状态机: {key}")
                        router = router_cls()
                        cls._validate_router(router)
                        engine = StateMachine(router)
                    cls._engines[key] = engine
        return engine
