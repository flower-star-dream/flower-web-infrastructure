"""
模型配置来源注册表

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 模型配置来源 SPI 注册表（AI 规范 §2/§3/§17.4）：
              按 store 名注册/查询 ModelConfigStoreInterface 工厂，装配期（app.ai.store.type）
              按名实例化；内置 yml 条目，用户自定义来源（配置中心/Redis 等）经 register
              注册后即可接入 create_app，无需改动框架装配代码。
"""
from __future__ import annotations

from threading import Lock
from typing import Callable, ClassVar

from web_infra.capabilities.ai.dict_model_config_store import DictModelConfigStore
from web_infra.capabilities.ai.model_config_store_interface import ModelConfigStoreInterface

#: store 工厂签名：无参调用返回模型配置来源实例（装配期由 create_app 调用）
StoreFactory = Callable[[], ModelConfigStoreInterface]


class ModelConfigStoreRegistry:
    """模型配置来源注册表（类级注册，全局装配；同名覆盖）"""

    _factories: ClassVar[dict[str, StoreFactory]] = {}
    _lock = Lock()

    @classmethod
    def register(cls, name: str, factory: StoreFactory) -> None:
        """注册模型配置来源工厂（同名覆盖）。

        :param name: store 名（与 yml app.ai.store.type 匹配）
        :param factory: 无参工厂，返回 ModelConfigStoreInterface 实现
        """
        with cls._lock:
            cls._factories[name] = factory

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销 store（不存在时静默）"""
        with cls._lock:
            cls._factories.pop(name, None)

    @classmethod
    def get(cls, name: str) -> StoreFactory:
        """按名查询工厂；未注册抛 KeyError（装配期由 create_app 捕获转 ConfigError）"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory

    @classmethod
    def create(cls, name: str) -> ModelConfigStoreInterface:
        """按名实例化 store；未注册抛 KeyError"""
        with cls._lock:
            factory = cls._factories.get(name)
        if factory is None:
            raise KeyError(name)
        return factory()

    @classmethod
    def registered_names(cls) -> list[str]:
        """已注册 store 名清单"""
        with cls._lock:
            return list(cls._factories)


# 内置 store 条目（模块导入即注册，幂等）：yml 内存/清单实现
ModelConfigStoreRegistry.register("yml", lambda: DictModelConfigStore())
