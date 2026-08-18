"""
Feign 客户端配置模型与装配工厂（FeignClientConfig / build_feign_client）

@Author: 花海
@Date: 2026/08/16
@Description: 消除业务侧 FeignClient 装配参数散落：FeignClientConfig 收敛构造参数
              （默认值引用 InfraConstant，规范 §7 远程调用韧性），build_feign_client
              从配置源（settings，缺省全局 Settings）按前缀读取 app.feign.* 段装配
              FeignClient，熔断参数收敛于 app.feign.circuit_breaker.*（缺失则不启用熔断）。
              业务只需在 application.yml 声明 app.feign 段即可复用框架默认装配逻辑。
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

import httpx
from pydantic import BaseModel

from web_infra.infra.config import CompositeConfigSource, DictConfigSource, Settings
from web_infra.infra.constants.infra_constant import InfraConstant
from web_infra.capabilities.http.feign_client import FeignClient
from web_infra.capabilities.registry.service_registry_interface import ServiceRegistryInterface
from web_infra.infra.resilience.circuit_breaker_config import CircuitBreakerConfig


class FeignClientConfig(BaseModel):
    """Feign 客户端装配参数（默认值收敛于 InfraConstant，禁止散落裸值）"""

    timeout: float = InfraConstant.INFRA_HTTP_TIMEOUT_SECONDS
    # 尝试次数 = 1 次首次 + INFRA_CALL_MAX_RETRIES 次重试（规范 §7.2 默认最多重试 2 次）
    retries: int = InfraConstant.INFRA_CALL_MAX_RETRIES + 1
    retry_delay_base: float = InfraConstant.INFRA_CALL_RETRY_DELAY_BASE_SECONDS
    retry_delay_max: float = InfraConstant.INFRA_CALL_RETRY_DELAY_MAX_SECONDS
    max_connections: int = InfraConstant.INFRA_HTTP_MAX_CONNECTIONS
    max_keepalive_connections: int = InfraConstant.INFRA_HTTP_MAX_KEEPALIVE_CONNECTIONS


def build_feign_client(
    registry: ServiceRegistryInterface,
    settings: Settings | dict[str, Any] | None = None,
    prefix: str = "app.feign",
    fallback: Optional[Callable[[str], Awaitable[Optional[httpx.Response]] | Optional[httpx.Response]]] = None,
    url_validator: Optional[Callable[[str], None]] = None,
) -> FeignClient:
    """从配置源装配 FeignClient（配置驱动，规范 §7）

    读取 {prefix}.* 段（缺省 app.feign.*）：超时/重试/退避/连接池参数收敛于 FeignClientConfig，
    熔断参数收敛于 {prefix}.circuit_breaker.*（缺失则该段不启用熔断）；
    fallback / url_validator 为函数入参（yml 无法表达函数，由业务按需显式传入）。

    :param registry: 服务注册发现 SPI（必传）
    :param settings: 配置源（Settings 实例或 dict；缺省全局 Settings 实例）
    :param prefix: 配置段前缀（默认 app.feign）
    :param fallback: 降级回调，缺省采用框架默认兜底 default_service_fallback
    :param url_validator: 目标地址校验钩子（SSRF 防护，默认不启用）
    :return: FeignClient 实例
    """
    source = _normalize_settings(settings)
    config = FeignClientConfig(
        **{
            name: source.get(f"{prefix}.{name}")
            for name in FeignClientConfig.model_fields
            if source.get(f"{prefix}.{name}") is not None
        }
    )
    return FeignClient(
        registry=registry,
        timeout=config.timeout,
        retries=config.retries,
        retry_delay_base=config.retry_delay_base,
        retry_delay_max=config.retry_delay_max,
        max_connections=config.max_connections,
        max_keepalive_connections=config.max_keepalive_connections,
        circuit_breaker_config=_build_circuit_breaker_config(source, prefix),
        fallback=fallback,
        url_validator=url_validator,
    )


def _normalize_settings(settings: Settings | dict[str, Any] | None) -> Settings:
    """归一化配置源入参：Settings 实例直接使用；None 用全局实例；dict 叠加默认源保证默认值回落"""
    if settings is None:
        return Settings.instance()
    if isinstance(settings, Settings):
        return settings
    return Settings(CompositeConfigSource(DictConfigSource(settings), Settings.default_source()))


def _build_circuit_breaker_config(settings: Any, prefix: str) -> CircuitBreakerConfig | None:
    """从配置读取 {prefix}.circuit_breaker 段构造熔断参数（缺失/空段返回 None 不启用熔断）"""
    values = settings.get(f"{prefix}.circuit_breaker")
    if not isinstance(values, dict) or not values:
        return None
    kwargs = {
        name: values[name] for name in CircuitBreakerConfig.__dataclass_fields__ if name in values
    }
    return CircuitBreakerConfig(**kwargs)
