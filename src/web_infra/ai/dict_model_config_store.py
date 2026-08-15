"""
内存模型配置来源

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 内存/字典模型配置来源（默认实现）。
"""
from __future__ import annotations

from web_infra.ai.model_config import ModelConfig
from web_infra.ai.model_config_store_interface import ModelConfigStoreInterface


class DictModelConfigStore(ModelConfigStoreInterface):
    """内存/字典模型配置来源（默认实现）"""

    def __init__(self, configs: dict[str, ModelConfig] | None = None, default_code: str | None = None) -> None:
        self._configs = configs or {}
        self._default_code = default_code

    async def load(self, model_code: str | None = None) -> ModelConfig | None:
        code = model_code or self._default_code
        if code:
            return self._configs.get(code)
        return next(iter(self._configs.values()), None)

    async def load_all(self) -> list[ModelConfig]:
        """加载全部模型配置"""
        return list(self._configs.values())
