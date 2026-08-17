"""
Feign 客户端配置装配单元测试

@Author: 花海
@Date: 2026/08/16
@Description: 验证 build_feign_client 配置驱动装配（规范 §7）：app.feign 段读取超时/重试/退避/熔断参数，
              缺失时回落 FeignClientConfig 默认值（引用 InfraConstant），circuit_breaker 段缺失不启用熔断。
"""
from __future__ import annotations

import pytest

from web_infra.http import FeignClientConfig, build_feign_client
from web_infra.registry import InMemoryServiceRegistry


def _settings(overrides: dict) -> dict:
    """构造配置源（嵌套结构，与 yml 一致：app.feign 段与覆盖项）"""
    return {"app": {"feign": overrides}}


@pytest.mark.asyncio
async def test_build_feign_client_from_settings():
    """app.feign 段配置完整映射到 FeignClient（超时/尝试次数/退避/熔断）"""
    registry = InMemoryServiceRegistry()
    client = build_feign_client(
        registry,
        settings=_settings(
            {
                "timeout": 10.0,
                "retries": 2,
                "retry_delay_base": 0.5,
                "retry_delay_max": 4.0,
                "circuit_breaker": {
                    "minimum_number_of_calls": 5,
                    "window_size": 10,
                    "wait_duration_in_open_state": 30.0,
                },
            }
        ),
    )
    try:
        assert client.retries == 2
        assert client.retry_delay_base == 0.5
        assert client.retry_delay_max == 4.0
        # 熔断参数经 app.feign.circuit_breaker 段装配
        breaker_config = client._circuit_breaker_config
        assert breaker_config is not None
        assert breaker_config.minimum_number_of_calls == 5
        assert breaker_config.window_size == 10
        assert breaker_config.wait_duration_in_open_state == 30.0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_build_feign_client_defaults_fallback_to_infra_constant():
    """无 app.feign 配置段时回落 FeignClientConfig 默认值（引用 InfraConstant，非散落裸值）"""
    from web_infra.constants.infra_constant import InfraConstant

    registry = InMemoryServiceRegistry()
    client = build_feign_client(registry, settings={})
    try:
        # 尝试次数 = 1 次首次 + INFRA_CALL_MAX_RETRIES 次重试
        assert client.retries == InfraConstant.INFRA_CALL_MAX_RETRIES + 1
        assert client.retry_delay_base == InfraConstant.INFRA_CALL_RETRY_DELAY_BASE_SECONDS
        assert client.retry_delay_max == InfraConstant.INFRA_CALL_RETRY_DELAY_MAX_SECONDS
        # 未配置熔断段：不启用熔断
        assert client._circuit_breaker_config is None
    finally:
        await client.close()


def test_feign_client_config_defaults_reference_infra_constant():
    """FeignClientConfig 默认值引用 InfraConstant（无魔法值）"""
    from web_infra.constants.infra_constant import InfraConstant

    config = FeignClientConfig()
    assert config.timeout == InfraConstant.INFRA_HTTP_TIMEOUT_SECONDS
    assert config.retries == InfraConstant.INFRA_CALL_MAX_RETRIES + 1
    assert config.retry_delay_base == InfraConstant.INFRA_CALL_RETRY_DELAY_BASE_SECONDS
    assert config.retry_delay_max == InfraConstant.INFRA_CALL_RETRY_DELAY_MAX_SECONDS
    assert config.max_connections == InfraConstant.INFRA_HTTP_MAX_CONNECTIONS
    assert config.max_keepalive_connections == InfraConstant.INFRA_HTTP_MAX_KEEPALIVE_CONNECTIONS
