"""
重试策略

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 远程调用重试，遵循规范 §7.2。
              仅幂等接口允许重试，退避策略为指数退避（exponential backoff），最大重试 2 次。
              仅对瞬时错误（网络错误、连接失败、超时等确定未产生副作用的场景）重试。
"""
from __future__ import annotations

import asyncio
import functools
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

# 返回值类型泛型
R = TypeVar("R")


@dataclass(frozen=True)
class RetryConfig:
    """重试配置（规范 §7.2：最大重试 2 次，指数退避）"""

    max_retries: int = 2
    base_delay: float = 0.5
    backoff_factor: float = 2.0


def _is_transient(exc: BaseException) -> bool:
    """判断是否为可重试的瞬时错误（网络/连接/超时，确定未产生副作用）"""
    try:
        import httpx  # 延迟导入，避免无 httpx 环境报错

        return isinstance(
            exc,
            (ConnectionError, TimeoutError, httpx.TimeoutException, httpx.TransportError),
        )
    except ImportError:
        return isinstance(exc, (ConnectionError, TimeoutError))


def retry(
    config: RetryConfig | None = None,
    *,
    retry_on: Callable[[BaseException], bool] = _is_transient,
):
    """重试装饰器：同时支持同步与异步函数，仅对满足 retry_on 的异常重试。

    注意：非幂等接口禁止重试（规范 §7.2），调用方应显式评估幂等性后再使用。
    """
    cfg = config or RetryConfig()

    def _decorator(func: Callable[..., R]) -> Callable[..., R]:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> R:
                last_exc: BaseException | None = None
                for attempt in range(cfg.max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:  # noqa: BLE001 - 需按重试策略判定
                        last_exc = exc
                        if attempt >= cfg.max_retries or not retry_on(exc):
                            raise
                        await asyncio.sleep(cfg.base_delay * (cfg.backoff_factor ** attempt))
                assert last_exc is not None
                raise last_exc

            return _async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> R:
            last_exc: BaseException | None = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt >= cfg.max_retries or not retry_on(exc):
                        raise
                    time.sleep(cfg.base_delay * (cfg.backoff_factor ** attempt))
            assert last_exc is not None
            raise last_exc

        return _sync_wrapper  # type: ignore[return-value]

    return _decorator
