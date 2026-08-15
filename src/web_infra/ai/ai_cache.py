"""
AI 缓存组件

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 大模型调用结果缓存（AI 规范 §8）：
              Key = SHA-256(prompt + 模型版本 + 关键参数 + 租户)（禁用 MD5），
              模型版本变更导致 Key 变化，实现自然失效；复用 CacheBackendInterface（内存/Redis）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from web_infra.cache.cache_backend_interface import CacheBackendInterface
from web_infra.cache.memory_cache_backend import MemoryCacheBackend


class AICache:
    """AI 调用结果缓存（语义缓存基础）"""

    def __init__(self, backend: CacheBackendInterface | None = None, key_prefix: str = "web:ai:v1:cache:") -> None:
        """初始化 AI 缓存。

        :param backend: 缓存后端（默认内存；多实例需注入 RedisCacheBackend）
        :param key_prefix: Key 前缀（含版本与业务域，规范 §5.7）
        """
        self._backend = backend or MemoryCacheBackend()
        self._key_prefix = key_prefix

    async def get(
        self,
        prompt: str,
        model_code: str,
        model_version: str,
        tenant_id: str = "",
        params: dict[str, Any] | None = None,
        user_id: str = "",
    ) -> str | None:
        """读取缓存命中结果。

        :param prompt: 用户提示词
        :param model_code: 模型编码
        :param model_version: 模型版本（参与 Key，版本变更自动失效）
        :param tenant_id: 租户标识（参与 Key，实现租户隔离）
        :param params: 影响结果的关键参数（如 temperature，参与 Key）
        :param user_id: 用户标识（参与 Key，防跨用户语义串扰；缺省不启用用户维度）
        :return: 命中的响应内容；未命中返回 None
        """
        key = self._build_key(prompt, model_code, model_version, tenant_id, params, user_id)
        return await self._backend.get(key)

    async def set(
        self,
        prompt: str,
        response: str,
        model_code: str,
        model_version: str,
        tenant_id: str = "",
        params: dict[str, Any] | None = None,
        user_id: str = "",
        ttl: int | None = None,
    ) -> None:
        """写入缓存。

        :param response: 模型响应内容
        :param user_id: 用户标识（参与 Key，与 get 一致）
        :param ttl: 有效期（秒），None 使用后端默认
        """
        key = self._build_key(prompt, model_code, model_version, tenant_id, params, user_id)
        await self._backend.set(key, response, ttl=ttl)

    def _build_key(
        self,
        prompt: str,
        model_code: str,
        model_version: str,
        tenant_id: str,
        params: dict[str, Any] | None,
        user_id: str = "",
    ) -> str:
        """构造缓存 Key：SHA-256 前 16 字节（32 hex，禁 MD5）+ 模型版本 + 关键参数 + 租户/用户维度（AI 规范 §8 / 多租户 §3）。

        Key 结构：{prefix}{tenant_id}:{digest}，租户维度明文可见、参与哈希隔离；
        user_id 参与哈希但不进明文前缀（避免 Key 过长），用于防止个性化 Prompt 跨用户串扰。
        """
        material = json.dumps(
            {
                "prompt": prompt,
                "model_code": model_code,
                "model_version": model_version,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "params": params or {},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        tenant = tenant_id or "no-tenant"
        return f"{self._key_prefix}{tenant}:{digest}"
