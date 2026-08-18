"""
Nacos SDK 客户端单元测试

@Author: 花海
@Date: 2026/08/15 15:00
@Description: 验证基于官方 nacos-sdk-python v2 的配置中心/注册中心客户端：
              ClientConfig 构建映射、配置拉取（异步/同步/失败兜底）、
              服务注册/注销/发现及实例转换。通过 mock SDK 入口避免真实 gRPC 连接。
"""
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("v2.nacos")

from v2.nacos import Instance, NacosConfigService, NacosNamingService  # noqa: E402

from web_infra.capabilities.config.nacos_client_factory import build_client_config  # noqa: E402
from web_infra.capabilities.config.nacos_config_client import NacosConfigClient  # noqa: E402
from web_infra.capabilities.config.nacos_properties import NacosProperties  # noqa: E402
from web_infra.capabilities.registry.nacos_discovery import NacosDiscoveryClient  # noqa: E402
from web_infra.capabilities.registry.service_instance import ServiceInstance  # noqa: E402


# ----------------------------------------------------------------------
# 客户端配置构建（NacosProperties -> ClientConfig）
# ----------------------------------------------------------------------


def test_build_client_config_mapping():
    """基础字段映射：地址/命名空间/账号/日志/超时/心跳"""
    props = NacosProperties(
        server_addresses="host1:8848,host2:8848",
        namespace="ns1",
        username="user",
        password="pass",
        log_level="DEBUG",
        grpc_timeout_ms=8000,
        heartbeat_interval=3,
    )
    config = build_client_config(props)
    assert config.server_list == ["host1:8848", "host2:8848"]
    assert config.namespace_id == "ns1"
    assert config.username == "user"
    assert config.password == "pass"
    assert config.log_level == "DEBUG"
    assert config.grpc_config.grpc_timeout == 8000
    assert config.heart_beat_interval == 3000


def test_build_client_config_tls():
    """TLS 配置映射"""
    props = NacosProperties(
        tls_enabled=True,
        tls_ca_file="/ca.pem",
        tls_cert_file="/cert.pem",
        tls_key_file="/key.pem",
    )
    config = build_client_config(props)
    assert config.tls_config.enabled is True
    assert config.tls_config.ca_file == "/ca.pem"
    assert config.tls_config.cert_file == "/cert.pem"
    assert config.tls_config.key_file == "/key.pem"


# ----------------------------------------------------------------------
# 配置中心客户端（NacosConfigClient）
# ----------------------------------------------------------------------


class _FakeConfigService:
    """模拟 NacosConfigService，仅暴露测试所需方法"""

    def __init__(self, content: str = "") -> None:
        self.get_config = AsyncMock(return_value=content)
        self.shutdown = AsyncMock()


def _patch_config_service(monkeypatch, fake: _FakeConfigService) -> None:
    """将 NacosConfigService.create_config_service 替换为返回 fake 的 mock"""
    monkeypatch.setattr(NacosConfigService, "create_config_service", AsyncMock(return_value=fake))


@pytest.mark.asyncio
async def test_config_get_config(monkeypatch):
    """异步拉取配置：透传 data_id/group 并返回内容"""
    fake = _FakeConfigService(content="key: value")
    _patch_config_service(monkeypatch, fake)
    client = NacosConfigClient(NacosProperties(server_addresses="localhost:8848"))
    content = await client.get_config("app.yml")
    assert content == "key: value"
    param = fake.get_config.call_args.args[0]
    assert param.data_id == "app.yml"
    assert param.group == "DEFAULT_GROUP"


@pytest.mark.asyncio
async def test_config_get_config_group_override(monkeypatch):
    """异步拉取配置：显式 group 覆盖默认分组"""
    fake = _FakeConfigService(content="x")
    _patch_config_service(monkeypatch, fake)
    client = NacosConfigClient(NacosProperties(server_addresses="localhost:8848"))
    await client.get_config("app.yml", "GROUP_A")
    param = fake.get_config.call_args.args[0]
    assert param.group == "GROUP_A"


@pytest.mark.asyncio
async def test_config_get_config_failure_returns_empty(monkeypatch):
    """拉取异常时返回空字符串（与旧行为一致）"""
    fake = _FakeConfigService()
    fake.get_config = AsyncMock(side_effect=RuntimeError("boom"))
    _patch_config_service(monkeypatch, fake)
    client = NacosConfigClient(NacosProperties(server_addresses="localhost:8848"))
    assert await client.get_config("app.yml") == ""


def test_config_get_config_sync(monkeypatch):
    """同步拉取配置（无运行中事件循环场景，如应用启动阶段）"""
    fake = _FakeConfigService(content="key: value")
    _patch_config_service(monkeypatch, fake)
    client = NacosConfigClient(NacosProperties(server_addresses="localhost:8848"))
    assert client.get_config_sync("app.yml", "GROUP_A") == "key: value"
    param = fake.get_config.call_args.args[0]
    assert param.data_id == "app.yml"
    assert param.group == "GROUP_A"


@pytest.mark.asyncio
async def test_config_get_config_sync_in_event_loop():
    """事件循环内调用同步方法：拒绝执行并返回空字符串（提示改用异步接口）"""
    client = NacosConfigClient(NacosProperties(server_addresses="localhost:8848"))
    assert client.get_config_sync("app.yml") == ""


@pytest.mark.asyncio
async def test_config_close(monkeypatch):
    """close 关闭并释放 SDK 连接，重复 close 幂等"""
    fake = _FakeConfigService()
    _patch_config_service(monkeypatch, fake)
    client = NacosConfigClient(NacosProperties(server_addresses="localhost:8848"))
    await client.get_config("app.yml")
    await client.close()
    fake.shutdown.assert_awaited_once()
    await client.close()  # 第二次 close 不重复关闭
    fake.shutdown.assert_awaited_once()


# ----------------------------------------------------------------------
# 注册中心客户端（NacosDiscoveryClient）
# ----------------------------------------------------------------------


class _FakeNamingService:
    """模拟 NacosNamingService，仅暴露测试所需方法"""

    def __init__(self) -> None:
        self.register_instance = AsyncMock(return_value=True)
        self.deregister_instance = AsyncMock(return_value=True)
        self.list_instances = AsyncMock(
            return_value=[
                Instance(ip="10.0.0.1", port=8080, weight=2.0, metadata={"region": "cn"}, healthy=True)
            ]
        )
        self.shutdown = AsyncMock()


def _patch_naming_service(monkeypatch, fake: _FakeNamingService) -> None:
    """将 NacosNamingService.create_naming_service 替换为返回 fake 的 mock"""
    monkeypatch.setattr(NacosNamingService, "create_naming_service", AsyncMock(return_value=fake))


@pytest.mark.asyncio
async def test_discovery_register(monkeypatch):
    """注册：构造 RegisterInstanceParam 并透传实例信息"""
    fake = _FakeNamingService()
    _patch_naming_service(monkeypatch, fake)
    client = NacosDiscoveryClient(NacosProperties(server_addresses="localhost:8848"))
    ok = await client.register("order", ServiceInstance(ip="10.0.0.1", port=8080, metadata={"a": "b"}))
    assert ok is True
    fake.register_instance.assert_awaited_once()
    request = fake.register_instance.call_args.args[0]
    assert request.service_name == "order"
    assert request.group_name == "DEFAULT_GROUP"
    assert request.ip == "10.0.0.1"
    assert request.port == 8080
    assert request.metadata == {"a": "b"}


@pytest.mark.asyncio
async def test_discovery_register_failure_returns_false(monkeypatch):
    """注册异常返回 False"""
    fake = _FakeNamingService()
    fake.register_instance = AsyncMock(side_effect=RuntimeError("boom"))
    _patch_naming_service(monkeypatch, fake)
    client = NacosDiscoveryClient(NacosProperties(server_addresses="localhost:8848"))
    assert await client.register("order", ServiceInstance(ip="10.0.0.1", port=8080)) is False


@pytest.mark.asyncio
async def test_discovery_get_instances(monkeypatch):
    """发现：SDK Instance 列表转换为框架 ServiceInstance"""
    fake = _FakeNamingService()
    _patch_naming_service(monkeypatch, fake)
    client = NacosDiscoveryClient(NacosProperties(server_addresses="localhost:8848"))
    found = await client.get_instances("order")
    assert len(found) == 1
    assert found[0].ip == "10.0.0.1"
    assert found[0].port == 8080
    assert found[0].weight == 2.0
    assert found[0].metadata == {"region": "cn"}
    assert found[0].healthy is True
    request = fake.list_instances.call_args.args[0]
    assert request.service_name == "order"
    assert request.healthy_only is True


@pytest.mark.asyncio
async def test_discovery_deregister(monkeypatch):
    """注销：构造 DeregisterInstanceParam 并透传实例信息"""
    fake = _FakeNamingService()
    _patch_naming_service(monkeypatch, fake)
    client = NacosDiscoveryClient(NacosProperties(server_addresses="localhost:8848"))
    ok = await client.deregister("order", ServiceInstance(ip="10.0.0.1", port=8080))
    assert ok is True
    fake.deregister_instance.assert_awaited_once()
    request = fake.deregister_instance.call_args.args[0]
    assert request.service_name == "order"
    assert request.ip == "10.0.0.1"
    assert request.port == 8080


@pytest.mark.asyncio
async def test_discovery_close(monkeypatch):
    """close 关闭并释放 SDK 连接，重复 close 幂等"""
    fake = _FakeNamingService()
    _patch_naming_service(monkeypatch, fake)
    client = NacosDiscoveryClient(NacosProperties(server_addresses="localhost:8848"))
    await client.register("order", ServiceInstance(ip="10.0.0.1", port=8080))
    await client.close()
    fake.shutdown.assert_awaited_once()
    await client.close()  # 第二次 close 不重复关闭
    fake.shutdown.assert_awaited_once()
