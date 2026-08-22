"""
声明式缓存

@Author: 花海
@Date: 2026/08/22 16:00
@Description: 声明式缓存装饰器（普通装饰器形态，不参与 AOP order 排序）：
              @cacheable 命中缓存直接返回，未命中回源并写缓存；
              @cache_evict 调用后删除缓存。
              基于 CacheBackendInterface（异步协议），Key 由 KeyBuilder 按模板 + 位置参数构建。
              注意：后端统一为异步接口，本装饰器仅支持 async 函数，同步函数装饰时直接报错，避免误用。
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from web_infra.capabilities.cache.key_builder import KeyBuilder
from web_infra.core.aop import get_component


def _build_key(key_template: str, args: tuple[Any, ...]) -> str:
    """按模板 + 位置参数构建缓存 Key（KeyBuilder 按位注入动态段）。"""
    return KeyBuilder.build(key_template, *args)


def cacheable(key_template: str, *, ttl: int | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """声明式缓存读取装饰器。

    命中缓存直接返回（防穿透：空值占位由后端 is_empty 语义区分），未命中回源并把结果写入缓存。

    :param key_template: 缓存 Key 模板（如 "order:{0}"，占位符按位置注入参数）
    :param ttl: 过期秒数（None 使用后端默认 TTL）
    :raises RuntimeError: 装饰同步函数，或运行时取不到 cache 组件（未 create_app / 未 bind_components）
    """

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(fn):
            # 后端为异步接口，同步函数无法正确读写缓存，直接拒绝装饰避免误用。
            raise RuntimeError("cacheable/cache_evict 仅支持 async 函数")

        @functools.wraps(fn)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = get_component("cache")
            if cache is None:
                raise RuntimeError("@cacheable 取不到 cache 组件：请先 create_app() 或 bind_components({'cache': ...})")
            key = _build_key(key_template, args)
            cached = await cache.get(key)
            if cached is not None:
                return cached
            value = await fn(*args, **kwargs)
            await cache.set(key, value, ttl=ttl)
            return value

        return _async_wrapper

    return _decorator


def cache_evict(key_template: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """声明式缓存删除装饰器。

    调用目标函数前先删除缓存键，避免写入后残留旧缓存（写入后置失效）。

    :param key_template: 缓存 Key 模板
    :raises RuntimeError: 装饰同步函数，或运行时取不到 cache 组件（未 create_app / 未 bind_components）
    """

    def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if not inspect.iscoroutinefunction(fn):
            # 后端为异步接口，同步函数无法正确读写缓存，直接拒绝装饰避免误用。
            raise RuntimeError("cacheable/cache_evict 仅支持 async 函数")

        @functools.wraps(fn)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = get_component("cache")
            if cache is None:
                raise RuntimeError("@cache_evict 取不到 cache 组件：请先 create_app() 或 bind_components({'cache': ...})")
            key = _build_key(key_template, args)
            await cache.delete(key)
            return await fn(*args, **kwargs)

        return _async_wrapper

    return _decorator
