"""
能力注册表测试

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 覆盖能力契约注册、依赖包含规则（用户系统 → 鉴权 → 支付，启用能力按包含关系自动带上前置）、
              拓扑解析（resolve）、装配校验（validate：未知能力/依赖循环）、启用（enable 自动导入框架模块）、
              业务自定义能力注册（以此类推）与 create_app 装配校验钩子（app.capabilities.enabled）。
"""
import importlib
import sys

import pytest

from web_infra import create_app
from web_infra.core.capability import (
    Capability,
    CapabilityError,
    CapabilityRegistry,
)
from web_infra.infra.config import ConfigError

# 测试专用业务能力名（避免与内置能力冲突）
TEST_ORDER = "test_order_cap"
TEST_CYCLE_A = "test_cycle_a"
TEST_CYCLE_B = "test_cycle_b"


def _register_test_capabilities() -> None:
    """注册测试专用能力（幂等）：业务订单能力依赖支付；循环依赖对用于装配校验。"""
    CapabilityRegistry.register(Capability(name=TEST_ORDER, modules=("web_infra.capabilities.payment",), requires=("pay",)))
    CapabilityRegistry.register(Capability(name=TEST_CYCLE_A, requires=(TEST_CYCLE_B,)))
    CapabilityRegistry.register(Capability(name=TEST_CYCLE_B, requires=(TEST_CYCLE_A,)))


_register_test_capabilities()


# ---------------------------------------------------------------------------
# 内置能力注册与依赖包含规则
# ---------------------------------------------------------------------------


def test_builtin_capabilities_registered():
    """内置能力已登记，且依赖包含规则符合 用户 → 认证 → 鉴权 → 支付"""
    assert {"user", "authn", "authz", "pay", "ai", "mq", "storage"} <= set(CapabilityRegistry.names())
    assert CapabilityRegistry.get("pay").requires == ("authz",)
    assert CapabilityRegistry.get("authz").requires == ("authn",)
    assert CapabilityRegistry.get("authn").requires == ("user",)
    assert CapabilityRegistry.get("user").requires == ()


def test_resolve_pay_includes_prerequisites():
    """启用支付按包含关系自动带上前置：user → authn → authz → pay（拓扑序）"""
    resolution = CapabilityRegistry.resolve("pay")
    assert [c.name for c in resolution.chain] == ["user", "authn", "authz", "pay"]
    assert resolution.modules == ("web_infra.capabilities.security", "web_infra.capabilities.payment")


def test_resolve_authn_includes_user():
    """认证与鉴权一样依赖用户系统前置：启用认证自动带出用户"""
    resolution = CapabilityRegistry.resolve("authn")
    assert [c.name for c in resolution.chain] == ["user", "authn"]
    assert resolution.modules == ("web_infra.capabilities.security",)


def test_resolve_unknown_raises():
    """解析未注册能力抛 CapabilityError"""
    with pytest.raises(CapabilityError):
        CapabilityRegistry.resolve("no_such_capability")


def test_register_self_dependency_raises():
    """能力不能依赖自身"""
    with pytest.raises(CapabilityError):
        CapabilityRegistry.register(Capability(name="test_self", requires=("test_self",)))


def test_register_empty_name_raises():
    """能力名不能为空"""
    with pytest.raises(CapabilityError):
        CapabilityRegistry.register(Capability(name=""))


# ---------------------------------------------------------------------------
# 装配校验（validate）
# ---------------------------------------------------------------------------


def test_validate_auto_includes_prerequisites():
    """装配校验：启用 pay 自动补足前置 authz/authn/user（缺前置不视为失败，按包含关系展开）"""
    validation = CapabilityRegistry.validate(["pay"])
    assert validation.ok
    assert validation.closure == frozenset({"user", "authn", "authz", "pay"})
    assert validation.chain == ("user", "authn", "authz", "pay")
    assert not validation.unknown
    assert not validation.circular


def test_validate_reports_unknown():
    """装配校验：未知能力 → ok=False 并给出明细"""
    validation = CapabilityRegistry.validate(["pay", "no_such_capability"])
    assert not validation.ok
    assert "no_such_capability" in validation.unknown
    assert validation.closure == frozenset({"user", "authn", "authz", "pay"})


def test_validate_reports_circular():
    """装配校验：依赖循环 → ok=False 并给出循环链路"""
    validation = CapabilityRegistry.validate([TEST_CYCLE_A])
    assert not validation.ok
    assert validation.circular


# ---------------------------------------------------------------------------
# 启用（enable，自动导入框架模块）
# ---------------------------------------------------------------------------


def test_enable_pay_imports_modules():
    """启用 pay 自动导入前置与目标框架模块（幂等）"""
    resolution = CapabilityRegistry.enable("pay")
    assert resolution.modules == ("web_infra.capabilities.security", "web_infra.capabilities.payment")
    assert "web_infra.capabilities.security" in sys.modules
    assert "web_infra.capabilities.payment" in sys.modules


def test_enable_user_no_modules():
    """用户系统为契约能力（业务实现）：无框架模块，启用仅完成解析校验"""
    resolution = CapabilityRegistry.enable("user")
    assert resolution.modules == ()
    assert [c.name for c in resolution.chain] == ["user"]


# ---------------------------------------------------------------------------
# 业务自定义能力（以此类推，业务层扩展）
# ---------------------------------------------------------------------------


def test_business_capability_registration():
    """业务层注册自定义能力（订单依赖支付），解析自动展开全部前置"""
    resolution = CapabilityRegistry.resolve(TEST_ORDER)
    assert [c.name for c in resolution.chain] == ["user", "authn", "authz", "pay", TEST_ORDER]
    assert resolution.modules == ("web_infra.capabilities.security", "web_infra.capabilities.payment")


# ---------------------------------------------------------------------------
# create_app 装配校验钩子（app.capabilities.enabled）
# ---------------------------------------------------------------------------


def test_create_app_capabilities_hook():
    """create_app 按 app.capabilities.enabled 启用能力（pay 自动带上前置）"""
    app = create_app({"app.capabilities.enabled": ["pay"]})
    assert app is not None


def test_create_app_capabilities_unknown_raises():
    """create_app 装配校验：未注册能力 → ConfigError"""
    with pytest.raises(ConfigError):
        create_app({"app.capabilities.enabled": ["no_such_capability"]})


def test_capability_top_level_export():
    """能力注册表随 web_infra 顶层导出（核心机制）"""
    from web_infra import CapabilityRegistry as TopLevelRegistry

    assert TopLevelRegistry is CapabilityRegistry
    assert importlib.import_module("web_infra.core.capability") is not None
