"""
SPI 注册表基类单元测试

@Author: 花海
@Date: 2026/08/22 12:00
@Description: 验证命名空间隔离、框架默认实现保护、同命名空间优先级与解析顺序（ns:name > user > framework）。
"""
import pytest

from web_infra.core.spi import SpiRegistry


@pytest.fixture(autouse=True)
def _clean_registry():
    """每用例后清空命名空间/实例/运行时切换存储，防止脏状态污染"""
    yield
    SpiRegistry._store().clear()
    SpiRegistry._inst_store().clear()
    SpiRegistry._active_store().clear()


def test_register_and_get_plain_name():
    """默认命名空间（user）注册与解析"""
    SpiRegistry.register("memory", lambda: "mem")
    assert SpiRegistry.get("memory")() == "mem"


def test_register_empty_name_raises():
    """空实现名拒绝注册"""
    with pytest.raises(ValueError):
        SpiRegistry.register("", lambda: None)


def test_duplicate_same_namespace_rejected_without_overwrite():
    """同命名空间同名默认拒绝（overwrite=False）"""
    SpiRegistry.register("memory", lambda: "a")
    with pytest.raises(ValueError):
        SpiRegistry.register("memory", lambda: "b")
    assert SpiRegistry.get("memory")() == "a"


def test_duplicate_same_namespace_overwrite_allowed():
    """显式 overwrite=True 允许同名覆盖"""
    SpiRegistry.register("memory", lambda: "a")
    SpiRegistry.register("memory", lambda: "b", overwrite=True)
    assert SpiRegistry.get("memory")() == "b"


def test_framework_default_protected_from_plain_registration():
    """框架命名空间默认受保护：直接同名注册不覆盖框架实现"""
    SpiRegistry.register("memory", lambda: "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    # 用户以默认命名空间注册同名：解析时 user 命中（业务覆盖生效），框架实现未被破坏
    SpiRegistry.register("memory", lambda: "user")
    assert SpiRegistry.get("memory")() == "user"
    # 框架命名空间条目仍存在（完整性校验可核验）
    assert "memory" in SpiRegistry.registered_framework_names()


def test_framework_ns_overwrite_requires_override():
    """直接向框架命名空间写入同名（不改 user）需 overwrite=True"""
    SpiRegistry.register("memory", lambda: "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    with pytest.raises(ValueError):
        SpiRegistry.register("memory", lambda: "x", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register("memory", lambda: "y", namespace=SpiRegistry.FRAMEWORK_NAMESPACE, overwrite=True)
    assert SpiRegistry.get("memory")() == "y"


def test_resolution_order_user_beats_framework():
    """解析顺序：user 命名空间命中优先于 framework 默认"""
    SpiRegistry.register("memory", lambda: "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register("memory", lambda: "user")
    assert SpiRegistry.get("memory")() == "user"


def test_resolution_order_explicit_namespace_wins():
    """显式 'ns:name' 限定命名空间优先"""
    SpiRegistry.register("memory", lambda: "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register("memory", lambda: "user")
    assert SpiRegistry.get("framework:memory")() == "fw"
    assert SpiRegistry.get("user:memory")() == "user"


def test_priority_within_namespace():
    """同命名空间内优先级越大越先命中"""
    SpiRegistry.register("memory", lambda: "low", priority=0)
    SpiRegistry.register("memory", lambda: "high", priority=10, overwrite=True)
    assert SpiRegistry.get("memory")() == "high"


def test_get_unregistered_raises_key_error():
    """未注册抛 KeyError（装配期由 _resolve_registry 转 ConfigError）"""
    with pytest.raises(KeyError):
        SpiRegistry.get("nope")


def test_unregister_removes_across_namespaces():
    """unregister 跨命名空间移除；'ns:name' 限定单命名空间"""
    SpiRegistry.register("memory", lambda: "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register("memory", lambda: "user")
    SpiRegistry.unregister("memory")
    with pytest.raises(KeyError):
        SpiRegistry.get("memory")
    SpiRegistry.register("memory", lambda: "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register("memory", lambda: "user")
    SpiRegistry.unregister("framework:memory")
    assert SpiRegistry.get("memory")() == "user"  # framework 已移除，user 命中


def test_registered_names_dedupe_across_namespaces():
    """registered_names 跨命名空间去重（用于错误提示）"""
    SpiRegistry.register("memory", lambda: "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register("memory", lambda: "user")
    assert SpiRegistry.registered_names() == ["memory"]


def test_registered_framework_names():
    """registered_framework_names 列框架命名空间实现（完整性命校验用）"""
    SpiRegistry.register("memory", lambda: "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    assert SpiRegistry.registered_framework_names() == ["memory"]


# ---------------------------------------------------------------------------
# 阶段 B：实例侧 + 运行时切换 + 统一解析入口 + 策略组合器回退
# ---------------------------------------------------------------------------


def test_instance_dual_namespace_isolated():
    """双实例隔离：frameework 与 user 同名各自注册不同实例，互不影响"""
    SpiRegistry.register_instance("memory", "fw-instance", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register_instance("memory", "user-instance")
    assert SpiRegistry.get_instance("framework:memory") == "fw-instance"
    assert SpiRegistry.get_instance("user:memory") == "user-instance"
    # 默认解析 user 优先
    assert SpiRegistry.get_instance("memory") == "user-instance"
    # 跨命名空间去重清单与 framework 清单
    assert SpiRegistry.registered_instance_names() == ["memory"]
    assert SpiRegistry.registered_framework_instance_names() == ["memory"]


def test_register_instance_duplicate_rejected_without_overwrite():
    """实例同名且未 overwrite 拒绝；overwrite=True 允许覆盖"""
    SpiRegistry.register_instance("memory", "a")
    with pytest.raises(ValueError):
        SpiRegistry.register_instance("memory", "b")
    assert SpiRegistry.get_instance("memory") == "a"
    SpiRegistry.register_instance("memory", "b", overwrite=True)
    assert SpiRegistry.get_instance("memory") == "b"


def test_unregister_instance_removes_across_namespaces():
    """unregister_instance 跨命名空间移除；'ns:name' 限定单命名空间"""
    SpiRegistry.register_instance("memory", "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register_instance("memory", "user")
    SpiRegistry.unregister_instance("memory")
    with pytest.raises(KeyError):
        SpiRegistry.get_instance("memory")
    SpiRegistry.register_instance("memory", "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register_instance("memory", "user")
    SpiRegistry.unregister_instance("framework:memory")
    assert SpiRegistry.get_instance("memory") == "user"


def test_resolve_ref_returns_instance_and_plain_uses_factory():
    """统一解析入口：'ref:' 前缀返回已注册实例；纯名走工厂实例化"""
    SpiRegistry.register_instance("myinst", "the-instance")
    assert SpiRegistry.resolve("ref:myinst") == "the-instance"
    SpiRegistry.register("memory", lambda x, y=0: (x, y))
    assert SpiRegistry.resolve("memory", 1, y=2) == (1, 2)


def test_runtime_switch_affects_get_instance():
    """运行时切换：activate 重定向解析；deactivate 恢复默认；显式 'ns:name' 绕过激活"""
    SpiRegistry.register_instance("memory", "A", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register_instance("memory", "B")
    # 默认 user 优先 → B；显式 framework → A
    assert SpiRegistry.get_instance("memory") == "B"
    assert SpiRegistry.get_instance("framework:memory") == "A"
    # 切换到 framework 实现 A
    SpiRegistry.activate("memory", "framework:memory")
    assert "memory" in SpiRegistry.active_names()
    assert SpiRegistry.get_instance("memory") == "A"
    # 显式 'framework:memory' 绕过激活 → 仍 A
    assert SpiRegistry.get_instance("framework:memory") == "A"
    # 再切回 user 实现 B
    SpiRegistry.activate("memory", "user:memory")
    assert SpiRegistry.get_instance("memory") == "B"
    # deactivate 恢复默认解析（user 优先 → B）
    SpiRegistry.deactivate("memory")
    assert SpiRegistry.active_names() == []
    assert SpiRegistry.get_instance("memory") == "B"


def test_runtime_switch_affects_get_factory():
    """运行时切换同样作用于 get 工厂解析"""
    SpiRegistry.register("memory", lambda: "fw", namespace=SpiRegistry.FRAMEWORK_NAMESPACE)
    SpiRegistry.register("memory", lambda: "user")
    assert SpiRegistry.get("memory")() == "user"
    SpiRegistry.activate("memory", "framework:memory")
    assert SpiRegistry.get("memory")() == "fw"
    SpiRegistry.deactivate("memory")
    assert SpiRegistry.get("memory")() == "user"


def test_fallback_uses_primary_when_no_error():
    """策略组合器：primary 工厂正常时直接返回其结果"""
    SpiRegistry.register("primary", lambda: "primary-ok")
    SpiRegistry.register("fallback", lambda: "fallback-ok")
    assert SpiRegistry.fallback("primary", "fallback")() == "primary-ok"


def test_fallback_switches_when_primary_raises():
    """策略组合器：primary 工厂抛错时回退 fallback 工厂正常返回"""
    def bad_factory():
        raise RuntimeError("boom")

    SpiRegistry.register("primary", bad_factory)
    SpiRegistry.register("fallback", lambda: "fallback-ok")
    assert SpiRegistry.fallback("primary", "fallback")() == "fallback-ok"


def test_get_instance_unregistered_raises_key_error():
    """未注册实例抛 KeyError"""
    with pytest.raises(KeyError):
        SpiRegistry.get_instance("nope")
