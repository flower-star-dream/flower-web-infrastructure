"""
熔断器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 熔断器实现，遵循规范 §7.4。
              按错误率（默认 50%）+ 慢调用比例（默认 80% 响应超 1s）双维度熔断。
              状态机：CLOSED -> OPEN -> HALF_OPEN -> CLOSED/OPEN。
              支持降级 fallback：熔断开启或调用异常时返回兜底结果（规范 §7.4 降级策略）。
"""
from __future__ import annotations

import asyncio
import inspect
import threading
import time
from collections import deque
from typing import Any, Callable, TypeVar

from web_infra.resilience.circuit_breaker_config import CircuitBreakerConfig
from web_infra.resilience.circuit_breaker_state_enum import CircuitBreakerState
from web_infra.resilience.circuit_open_error import CircuitOpenError

R = TypeVar("R")


class CircuitBreaker:
    """熔断器：按错误率 + 慢调用比例双维度统计，自动熔断与恢复，支持降级 fallback"""

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
        fallback: Callable[..., Any] | None = None,
    ) -> None:
        """初始化熔断器。

        :param name: 熔断器名称（按资源/服务维度隔离）
        :param config: 熔断参数（缺省用默认值）
        :param fallback: 降级回调，签名 `fallback(*args, **kwargs)`（与受保护调用同参）；
            同步调用配同步回调，异步调用可配同步或异步回调；熔断开启或调用异常时返回其结果，
            未配置时保持抛 CircuitOpenError / 原始异常
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._fallback = fallback
        self._state = CircuitBreakerState.CLOSED
        self._window: deque[tuple[bool, bool]] = deque(maxlen=self.config.window_size)  # (成功?, 慢?)
        self._open_until = 0.0
        self._half_open_inflight = 0
        # S16-2 豁免：临界区为纯内存操作，无 I/O 阻塞，不适用 3s 获取超时
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitBreakerState:
        """当前状态"""
        return self._state

    def can_execute(self) -> bool:
        """判断是否允许执行调用（OPEN 且未到等待时间则拒绝）"""
        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if time.monotonic() >= self._open_until:
                    # 进入半开状态尝试恢复
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_inflight = 0
                else:
                    return False
            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_inflight >= self.config.permitted_calls_in_half_open_state:
                    return False
                self._half_open_inflight += 1
            return True

    def _record(self, success: bool, slow: bool) -> None:
        """记录一次调用结果并评估是否触发熔断"""
        with self._lock:
            self._window.append((success, slow))
            if self._state == CircuitBreakerState.HALF_OPEN:
                # 半开探测调用完成：回收许可并决定恢复/重新熔断
                self._half_open_inflight = max(0, self._half_open_inflight - 1)
                if success:
                    # 探测成功：熔断器恢复关闭并重置统计窗口（HALF_OPEN → CLOSED）
                    self._state = CircuitBreakerState.CLOSED
                    self._window.clear()
                else:
                    # 探测失败：重新熔断开启，等待下一个恢复周期
                    self._state = CircuitBreakerState.OPEN
                    self._open_until = time.monotonic() + self.config.wait_duration_in_open_state
                return

            if self._state == CircuitBreakerState.OPEN:
                return

            total = len(self._window)
            if total < self.config.minimum_number_of_calls:
                return

            failures = sum(1 for ok, _ in self._window if not ok)
            slow_calls = sum(1 for _, sl in self._window if sl)
            failure_rate = failures / total
            slow_rate = slow_calls / total

            if failure_rate >= self.config.failure_rate_threshold or slow_rate >= self.config.slow_call_rate_threshold:
                self._state = CircuitBreakerState.OPEN
                self._open_until = time.monotonic() + self.config.wait_duration_in_open_state

    def _run_fallback(self, *args: Any, **kwargs: Any) -> Any:
        """执行降级回调（未配置 fallback 时抛 CircuitOpenError，保持原语义）"""
        if self._fallback is None:
            raise CircuitOpenError(f"熔断器 {self.name} 已开启")
        result = self._fallback(*args, **kwargs)
        if inspect.isawaitable(result):
            raise TypeError("同步调用不能使用异步 fallback，请改用 execute_async")
        return result

    async def _run_fallback_async(self, *args: Any, **kwargs: Any) -> Any:
        """异步执行降级回调（支持同步/异步 fallback；未配置时抛 CircuitOpenError）"""
        if self._fallback is None:
            raise CircuitOpenError(f"熔断器 {self.name} 已开启")
        result = self._fallback(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    def _execute_sync(self, func: Callable[..., R], *args: Any, **kwargs: Any) -> R:
        """同步执行并记录结果；熔断开启或（配置了 fallback 时）调用异常降级"""
        if not self.can_execute():
            return self._run_fallback(*args, **kwargs)
        start = time.monotonic()
        try:
            result = func(*args, **kwargs)
        except Exception:
            self._record(False, time.monotonic() - start > self.config.slow_call_duration_threshold)
            if self._fallback is None:
                raise  # 未配置 fallback：保持原始异常上抛
            return self._run_fallback(*args, **kwargs)
        except BaseException:
            # BaseException（如 KeyboardInterrupt）：同样记录结果以回收半开许可，再按原语义传播
            self._record(False, time.monotonic() - start > self.config.slow_call_duration_threshold)
            raise
        self._record(True, time.monotonic() - start > self.config.slow_call_duration_threshold)
        return result

    async def _execute_async(self, func: Callable[..., Awaitable[R]], *args: Any, **kwargs: Any) -> R:
        """异步执行并记录结果；熔断开启或（配置了 fallback 时）调用异常降级"""
        if not self.can_execute():
            return await self._run_fallback_async(*args, **kwargs)
        start = time.monotonic()
        try:
            result = await func(*args, **kwargs)
        except asyncio.CancelledError:
            # 调用被取消（任务取消/客户端断开）：CancelledError 继承 BaseException，
            # 不会被 except Exception 捕获；此处先记录结果回收半开许可，再按取消语义传播，
            # 防止 _half_open_inflight 永久泄漏导致熔断器在 HALF_OPEN 阶段无法恢复
            self._record(False, time.monotonic() - start > self.config.slow_call_duration_threshold)
            raise
        except Exception:
            self._record(False, time.monotonic() - start > self.config.slow_call_duration_threshold)
            if self._fallback is None:
                raise  # 未配置 fallback：保持原始异常上抛
            return await self._run_fallback_async(*args, **kwargs)
        self._record(True, time.monotonic() - start > self.config.slow_call_duration_threshold)
        return result

    def execute(self, func: Callable[..., R], *args: Any, **kwargs: Any) -> R:
        """执行受熔断保护的调用（自动识别同步/异步函数）"""
        import asyncio

        if asyncio.iscoroutinefunction(func):
            raise TypeError("异步函数请使用 execute_async")
        return self._execute_sync(func, *args, **kwargs)

    async def execute_async(self, func: Callable[..., R], *args: Any, **kwargs: Any) -> R:
        """异步执行受熔断保护的调用"""
        return await self._execute_async(func, *args, **kwargs)
