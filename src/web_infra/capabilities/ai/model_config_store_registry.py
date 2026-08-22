"""
模型配置来源注册表

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 模型配置来源 SPI 注册表（AI 规范 §2/§3/§17.4）：
              按 store 名注册/查询 ModelConfigStoreInterface 工厂，装配期（app.ai.store.type）
              按名实例化；内置 yml 条目，用户自定义来源（配置中心/Redis 等）经 register
              注册后即可接入 create_app，无需改动框架装配代码。
              继承 SpiRegistry 基类：内置默认落框架命名空间（受保护），用户同名覆盖经默认命名空间解析。
"""
from __future__ import annotations

from typing import Callable

from web_infra.capabilities.ai.dict_model_config_store import DictModelConfigStore
from web_infra.capabilities.ai.model_config_store_interface import ModelConfigStoreInterface
from web_infra.core.spi import SpiRegistry

#: store 工厂签名：无参调用返回模型配置来源实例（装配期由 create_app 调用）
StoreFactory = Callable[[], ModelConfigStoreInterface]


class ModelConfigStoreRegistry(SpiRegistry):
    """模型配置来源注册表（类级注册，全局装配；同名覆盖）"""

    @classmethod
    def create(cls, name: str) -> ModelConfigStoreInterface:
        """按名实例化 store；未注册抛 KeyError"""
        return cls.get(name)()


# 内置 store 条目（模块导入即注册，幂等）：yml 内存/清单实现
ModelConfigStoreRegistry.register(
    "yml", lambda: DictModelConfigStore(), namespace=ModelConfigStoreRegistry.FRAMEWORK_NAMESPACE
)
