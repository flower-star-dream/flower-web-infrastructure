"""
Feign 风格 HTTP 客户端

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 声明式服务间 HTTP 客户端，遵循规范 §7（远程调用韧性）。
              基于 httpx 实现服务发现 + 负载均衡 + 指数退避重试 + 连接池 + 熔断降级（§7.4），
              业务代码只依赖 ServiceRegistryInterface SPI。
              链路头注入（规范 §6.4）：发起请求前自动注入 X-Service-Id/X-User-Id/X-Trace-Id 等
              链路头，并剥离调用方透传的 Authorization 用户凭证头（服务间调用禁止裸传用户凭证）；
              SSRF 防护（规范 §25.3）：提供可插拔 url_validator 目标地址校验钩子（默认不启用）。
"""
from __future__ import annotations

import asyncio
import ipaddress
import random
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

import httpx

from web_infra.constants import AuthConstant, HttpStatusConstant
from web_infra.context import RequestContext
from web_infra.constants.infra_constant import InfraConstant
from web_infra.error.common_error_code import CommonErrorCode
from web_infra.loadbalance import LoadBalancerInterface, RoundRobinBalancer
from web_infra.registry.service_registry_interface import ServiceRegistryInterface
from web_infra.resilience.circuit_breaker import CircuitBreaker
from web_infra.resilience.circuit_breaker_config import CircuitBreakerConfig


def default_url_validator(url: str) -> None:
    """默认目标地址校验器（规范 §25.3 SSRF 防护示例）：拒绝私有网段/内网 IP/127.0.0.1/localhost。

    注意：默认不启用（FeignClient.url_validator 缺省 None），由业务显式传入本函数或更强校验器
    后生效，避免破坏既有内网服务调用；业务应结合自身网络拓扑注入更严格的校验。
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        raise ValueError(f"目标地址缺少有效主机名: {url}")
    # 拒绝 localhost / 回环地址
    if host in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(f"禁止访问内网/本地地址: {host}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # 域名不做 IP 段校验（默认校验器为示例），业务可注入更强校验
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        raise ValueError(f"禁止访问内网/保留网段地址: {host}")


def default_service_fallback(service_name: str) -> httpx.Response:
    """框架默认服务降级兜底（规范 §7.4）：返回统一"服务不可用"响应（HTTP 503 + SYS_UNAVAILABLE）。

    供 FeignClient 启用熔断且未显式传 fallback 时使用，避免业务反复实现兜底；
    业务需自定义降级（如返回缓存数据）时，在构造 FeignClient 时传 fallback 参数覆盖即可。

    :param service_name: 目标服务名（熔断按服务维度隔离，兜底响应中携带以定位）
    :return: 统一降级响应（code=E5-SYS-002 / message=服务 <name> 暂不可用 / HTTP 503）
    """
    return httpx.Response(
        CommonErrorCode.SYS_UNAVAILABLE.http_status,
        json={
            "code": CommonErrorCode.SYS_UNAVAILABLE.code,
            "message": f"服务 {service_name} 暂不可用",
        },
    )


class FeignClient:
    """Feign 风格 HTTP 客户端：服务发现 + 负载均衡 + 重试 + 连接池 + 熔断降级（未传 fallback 时默认兜底）"""

    def __init__(
        self,
        registry: ServiceRegistryInterface,
        load_balancer: Optional[LoadBalancerInterface] = None,
        timeout: float = InfraConstant.INFRA_HTTP_TIMEOUT_SECONDS,
        # 尝试次数 = 1 次首次 + INFRA_CALL_MAX_RETRIES 次重试（规范 §7.2 默认最多重试 2 次）
        retries: int = InfraConstant.INFRA_CALL_MAX_RETRIES + 1,
        retry_delay_base: float = InfraConstant.INFRA_CALL_RETRY_DELAY_BASE_SECONDS,
        retry_delay_max: float = InfraConstant.INFRA_CALL_RETRY_DELAY_MAX_SECONDS,
        max_connections: int = InfraConstant.INFRA_HTTP_MAX_CONNECTIONS,
        max_keepalive_connections: int = InfraConstant.INFRA_HTTP_MAX_KEEPALIVE_CONNECTIONS,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        fallback: Optional[Callable[[str], Awaitable[Optional[httpx.Response]] | Optional[httpx.Response]]] = None,
        url_validator: Optional[Callable[[str], None]] = None,
    ) -> None:
        """初始化 Feign 客户端。

        :param registry: 服务注册发现 SPI（get_instances(service_name)）
        :param load_balancer: 负载均衡策略（默认轮询）
        :param timeout: HTTP 请求超时（秒）
        :param retries: 最大尝试次数（首次 + 重试）
        :param retry_delay_base/retry_delay_max: 指数退避参数（含抖动）
        :param max_connections/max_keepalive_connections: 连接池上限
        :param circuit_breaker_config: 熔断参数；None 表示不启用熔断（默认）
        :param fallback: 降级回调 `fallback(service_name)`（可同步或异步，返回 httpx.Response 或 None），
            仅熔断开启时生效；未提供时采用框架默认兜底 default_service_fallback
            （统一 HTTP 503 + SYS_UNAVAILABLE"服务不可用"响应），业务可按需传参自定义降级
        :param url_validator: 目标地址校验钩子（规范 §25.3 SSRF 防护，如 default_url_validator）；
            缺省 None 不校验（保持既有内网服务调用兼容），业务按需注入更强校验
        """
        self.registry = registry
        self.load_balancer = load_balancer or RoundRobinBalancer()
        self.retries = retries
        self.retry_delay_base = retry_delay_base
        self.retry_delay_max = retry_delay_max
        self._circuit_breaker_config = circuit_breaker_config
        # 降级兜底：未显式传 fallback 时使用框架默认实现（统一 503 服务不可用），避免业务反复实现
        self._fallback = fallback or default_service_fallback
        self._url_validator = url_validator
        self._breakers: dict[str, CircuitBreaker] = {}
        limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_keepalive_connections)
        self._client = httpx.AsyncClient(timeout=timeout, limits=limits)

    async def close(self) -> None:
        """关闭 HTTP 连接池"""
        await self._client.aclose()

    def _get_breaker(self, service_name: str) -> CircuitBreaker:
        """按目标服务获取（并按需创建）熔断器，降级回调绑定服务名（§7.4 按服务维度熔断）"""
        breaker = self._breakers.get(service_name)
        if breaker is None:
            fallback = None
            fallback_cb = self._fallback
            if fallback_cb is not None:
                def _fallback(*args: Any, **kwargs: Any) -> Any:
                    return fallback_cb(service_name)
                fallback = _fallback
            breaker = CircuitBreaker(service_name, self._circuit_breaker_config, fallback=fallback)
            self._breakers[service_name] = breaker
        return breaker

    def _calculate_retry_delay(self, attempt: int) -> float:
        """指数退避 + 抖动（退避 = min(base * 2^attempt * jitter, max)，规范 §7.2）"""
        jitter = random.uniform(
            InfraConstant.INFRA_CALL_RETRY_JITTER_MIN, InfraConstant.INFRA_CALL_RETRY_JITTER_MAX
        )
        return min(self.retry_delay_base * (2 ** attempt) * jitter, self.retry_delay_max)

    def _is_retriable_error(self, exc: Exception) -> bool:
        """判断是否可重试（连接/超时/5xx/429）"""
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return (
                exc.response.status_code >= HttpStatusConstant.HTTP_SERVER_ERROR_MIN
                or exc.response.status_code == HttpStatusConstant.HTTP_TOO_MANY_REQUESTS
            )
        return False

    async def request(
        self,
        service_name: str,
        method: str,
        path: str,
        json_data: Any = None,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> httpx.Response | None:
        """发送请求，自动服务发现 + 负载均衡 + 重试；启用熔断时 OPEN/异常走 fallback 降级（可能返回 None）"""
        if self._circuit_breaker_config is None:
            return await self._request_with_retry(service_name, method, path, json_data=json_data, params=params, headers=headers)
        breaker = self._get_breaker(service_name)
        # 注：下方 type: ignore[reportReturnType] 为 pyright 对 await 泛型协程（execute_async[Callable[..., R]] -> R）
        # 的已知推断局限——R 被绑定为 CoroutineType 而非 unwrap 后的 Response；运行行为不受影响
        return await breaker.execute_async(  # type: ignore[reportReturnType]
            self._request_with_retry,
            service_name, method, path,
            json_data=json_data, params=params, headers=headers,
        )

    async def _request_with_retry(
        self,
        service_name: str,
        method: str,
        path: str,
        json_data: Any = None,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        """单次业务调用：服务发现 + 负载均衡 + 指数退避重试"""
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                instances = await self.registry.get_instances(service_name)
                if not instances:
                    raise CommonErrorCode.SYS_UNAVAILABLE.to_exception(message=f"服务 {service_name} 无可用实例")
                instance = self.load_balancer.choose(instances)
                url = f"{instance.url}{path}"
                # 目标地址校验（规范 §25.3 SSRF 防护）：业务注入 url_validator 时校验，默认不启用
                if self._url_validator is not None:
                    self._url_validator(url)
                # 服务链路头注入 + 剥离用户凭证头（规范 §6.4）
                final_headers = self._build_service_headers(headers)
                resp = await self._client.request(method=method, url=url, json=json_data, params=params, headers=final_headers)
                return resp
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt >= self.retries - 1 or not self._is_retriable_error(e):
                    break
                await asyncio.sleep(self._calculate_retry_delay(attempt))

        raise CommonErrorCode.SYS_INTERNAL.to_exception(message=f"服务 {service_name} 调用失败: {last_error}")

    def _build_service_headers(self, headers: dict | None) -> dict | None:
        """构造服务间调用请求头（规范 §6.4 服务内部调用链路头）：

        - 从请求上下文（RequestContext）自动注入 X-Service-Id/X-User-Id/X-Trace-Id/X-Client-Id/
          X-Tenant-Id/X-Scope（上下文无值则跳过注入，不抛错）；
        - 剥离调用方透传的 Authorization 用户凭证头（服务间调用禁止裸传用户凭证，
          改为注入服务身份头标识调用方）。
        """
        merged = dict(headers or {})
        merged.pop(AuthConstant.AUTH_HEADER_AUTHORIZATION, None)
        snapshot = RequestContext.snapshot()
        injected = {
            AuthConstant.AUTH_HEADER_SERVICE_ID: snapshot.service_id,
            AuthConstant.AUTH_HEADER_USER_ID: snapshot.user_id,
            AuthConstant.AUTH_HEADER_TRACE_ID: snapshot.trace_id,
            AuthConstant.AUTH_HEADER_CLIENT_ID: snapshot.client_id,
            AuthConstant.AUTH_HEADER_TENANT_ID: snapshot.tenant_id,
            AuthConstant.AUTH_HEADER_SCOPE: snapshot.scope,
        }
        for header, value in injected.items():
            if value:
                merged[header] = value
        return merged or None

    async def get(self, service_name: str, path: str, **kwargs: Any) -> httpx.Response | None:
        """GET 请求"""
        return await self.request(service_name, "GET", path, **kwargs)

    async def post(self, service_name: str, path: str, **kwargs: Any) -> httpx.Response | None:
        """POST 请求"""
        return await self.request(service_name, "POST", path, **kwargs)

    async def put(self, service_name: str, path: str, **kwargs: Any) -> httpx.Response | None:
        """PUT 请求"""
        return await self.request(service_name, "PUT", path, **kwargs)

    async def delete(self, service_name: str, path: str, **kwargs: Any) -> httpx.Response | None:
        """DELETE 请求"""
        return await self.request(service_name, "DELETE", path, **kwargs)
