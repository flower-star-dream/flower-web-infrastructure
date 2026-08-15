"""
服务注册发现单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证内存服务注册发现的注册/发现/注销行为，以及 Nacos 注册对外 IP 的分级探测
              （容器/多网卡场景下容器内部 IP 外部不可达，需优先采用显式配置或平台注入的 IP）。
"""
import socket
from unittest.mock import AsyncMock

import pytest

from web_infra.config.nacos_properties import NacosProperties
from web_infra.registry import InMemoryServiceRegistry, NacosRegistration, ServiceInstance


@pytest.fixture(autouse=True)
def _clear_register_env(monkeypatch):
    """清理影响 IP 探测的环境变量，保证测试隔离"""
    for key in ("NACOS_REGISTER_IP", "POD_IP", "HOST_IP"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.asyncio
async def test_register_and_discover():
    """注册后可通过服务名发现"""
    registry = InMemoryServiceRegistry()
    instance = ServiceInstance(ip="127.0.0.1", port=8000)
    await registry.register("order", instance)

    found = await registry.get_instances("order")
    assert len(found) == 1
    assert found[0].ip == "127.0.0.1"
    assert found[0].port == 8000


@pytest.mark.asyncio
async def test_deregister():
    """注销后不再被发现"""
    registry = InMemoryServiceRegistry()
    instance = ServiceInstance(ip="127.0.0.1", port=8000)
    await registry.register("order", instance)
    await registry.deregister("order", instance)

    assert await registry.get_instances("order") == []


def test_service_instance_host_url():
    """服务实例 host/url 属性"""
    instance = ServiceInstance(ip="10.0.0.1", port=8080)
    assert instance.host == "10.0.0.1:8080"
    assert instance.url == "http://10.0.0.1:8080"


# ----------------------------------------------------------------------
# Nacos 注册对外 IP 分级探测（容器场景）
# ----------------------------------------------------------------------


def test_register_ip_from_properties():
    """配置 register_ip 优先级最高"""
    reg = NacosRegistration(NacosProperties(register_ip="10.0.0.10"))
    assert reg._get_local_ip() == "10.0.0.10"


def test_register_ip_from_nacos_env(monkeypatch):
    """环境变量 NACOS_REGISTER_IP（保持向后兼容）"""
    monkeypatch.setenv("NACOS_REGISTER_IP", "10.0.0.11")
    reg = NacosRegistration(NacosProperties())
    assert reg._get_local_ip() == "10.0.0.11"


def test_register_ip_from_pod_env(monkeypatch):
    """K8s 场景使用 POD_IP"""
    monkeypatch.setenv("POD_IP", "10.244.0.5")
    reg = NacosRegistration(NacosProperties())
    assert reg._get_local_ip() == "10.244.0.5"


def test_register_ip_from_host_env(monkeypatch):
    """Docker 场景使用运维注入的 HOST_IP（宿主机 IP）"""
    monkeypatch.setenv("HOST_IP", "192.168.1.100")
    reg = NacosRegistration(NacosProperties())
    assert reg._get_local_ip() == "192.168.1.100"


def test_register_ip_from_default_gateway(monkeypatch):
    """无配置时回退默认网关（容器 bridge 下为宿主机地址）"""
    monkeypatch.setattr(NacosRegistration, "_get_default_gateway", staticmethod(lambda: "172.17.0.1"))
    reg = NacosRegistration(NacosProperties())
    assert reg._get_local_ip() == "172.17.0.1"


def test_register_ip_udp_probe(monkeypatch):
    """无配置且无网关时 UDP 探测本机出网 IP"""
    monkeypatch.setattr(NacosRegistration, "_get_default_gateway", staticmethod(lambda: None))

    class _FakeSocket:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self, addr):
            pass

        def getsockname(self):
            return ("10.0.0.5", 50000)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", _FakeSocket)
    reg = NacosRegistration(NacosProperties())
    assert reg._get_local_ip() == "10.0.0.5"


def test_register_ip_fallback_loopback(monkeypatch):
    """探测全部失败时回退 127.0.0.1"""
    monkeypatch.setattr(NacosRegistration, "_get_default_gateway", staticmethod(lambda: None))

    class _FakeSocket:
        def __init__(self, *args, **kwargs):
            pass

        def connect(self, addr):
            raise OSError("no route to host")

    monkeypatch.setattr(socket, "socket", _FakeSocket)
    reg = NacosRegistration(NacosProperties())
    assert reg._get_local_ip() == "127.0.0.1"


@pytest.mark.asyncio
async def test_register_explicit_ip_overrides_config(monkeypatch):
    """register() 显式传入 ip 参数优先于配置 register_ip"""
    reg = NacosRegistration(NacosProperties(register_ip="10.0.0.10"))
    monkeypatch.setattr(reg.discovery_client, "register", AsyncMock(return_value=True))

    await reg.register("order", 8000, ip="10.0.0.99")

    assert reg._instance is not None
    assert reg._instance.ip == "10.0.0.99"
