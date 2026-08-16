"""
模型配置管理器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 模型配置管理器：缓存 + 热刷新，依赖 ModelConfigStoreInterface SPI（AI 规范 §2/§3）。
              业务代码禁止硬编码模型密钥。
"""
from __future__ import annotations

import asyncio
from typing import Any

from web_infra.ai.model_config import ModelConfig
from web_infra.ai.model_config_store_interface import ModelConfigStoreInterface
from web_infra.error.ai_error_code import AiErrorCode


class ModelConfigManager:
    """模型配置管理器：缓存 + 热刷新，依赖 ModelConfigStoreInterface SPI"""

    def __init__(self, store: ModelConfigStoreInterface, cache: Any | None = None) -> None:
        self._store = store
        self._cache = cache
        self._lock = asyncio.Lock()

    async def get_config(self, model_code: str | None = None) -> ModelConfig:
        """获取模型配置（优先缓存，否则从 store 加载）"""
        config = await self._load_from_cache(model_code)
        if config is not None:
            return config
        async with self._lock:
            config = await self._load_from_cache(model_code)
            if config is not None:
                return config
            config = await self._store.load(model_code)
            if config is None:
                raise AiErrorCode.AI_NOT_CONFIGURED.to_exception(message=f"未找到模型配置: model_code={model_code}")
            await self._set_cache(model_code, config)
            return config

    async def refresh(self, model_code: str | None = None) -> ModelConfig:
        """强制刷新缓存并返回最新配置"""
        if self._cache is not None:
            try:
                await self._cache.delete(self._cache_key(model_code))
            except Exception:
                pass
        return await self.get_config(model_code)

    def _cache_key(self, model_code: str | None) -> str:
        return f"web:common:v1:model_config:{model_code or 'default'}"

    async def _load_from_cache(self, model_code: str | None) -> ModelConfig | None:
        if self._cache is None:
            return None
        data = await self._cache.get(self._cache_key(model_code))
        return ModelConfig(**data) if data else None

    async def _set_cache(self, model_code: str | None, config: ModelConfig) -> None:
        if self._cache is None:
            return
        await self._cache.set(self._cache_key(model_code), config.__dict__, ttl=300)
