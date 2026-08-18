"""
统一扩展注册器测试

@Author: 花海
@Date: 2026/08/18 14:00
@Description: 覆盖扩展点契约注册（同名默认拒绝/显式覆盖）、查询/注销、依赖解析（resolve 拓扑序）、
              装配校验（validate：未知扩展点/依赖循环）、create_app 装配钩子（app.extensions.enabled：
              实例挂 app.state.extensions、未知/循环快速失败、requires 前置自动启用）与生命周期编排
              （startup 拓扑序/停机逆序，同步/异步钩子皆可）。
"""
import pytest

from web_infra import create_app
from web_infra.config import ConfigError
from web_infra.extension import (
    ExtensionError,
    ExtensionPoint,
    ExtensionRegistry,
)

# 测试专用扩展点名（避免与业务/内置扩展点冲突）
TEST_EXT_A = "test_ext_a"
TEST_EXT_B = "test_ext_b"
TEST_EXT_PARENT = "test_ext_parent"
TEST_EXT_CHILD = "test_ext_child"
TEST_EXT_CYCLE_X = "test_ext_cycle_x"
TEST_EXT_CYCLE_Y = "test_ext_cycle_y"
TEST_EXT_OPT = "test_ext_opt"

#: 生命周期调用事件序列（build/startup/shutdown 顺序验证）
_LIFECYCLE_EVENTS: list[str] = []


def _build_a(options: dict, ctx: dict) -> str:
    _LIFECYCLE_EVENTS.append("build:test_ext_a")
    return "instance_a"


def _startup_a(instance) -> None:
    _LIFECYCLE_EVENTS.append(f"startup:{instance}")


async def _shutdown_a(instance) -> None:
    _LIFECYCLE_EVENTS.append(f"shutdown:{instance}")


def _build_parent(options: dict, ctx: dict) -> str:
    _LIFECYCLE_EVENTS.append("build:test_ext_parent")
    return "parent"


def _build_child(options: dict, ctx: dict) -> str:
    _LIFECYCLE_EVENTS.append("build:test_ext_child")
    return "child"


def _startup_child(instance) -> None:
    _LIFECYCLE_EVENTS.append(f"startup:{instance}")


def _shutdown_child(instance) -> None:
    _LIFECYCLE_EVENTS.append(f"shutdown:{instance}")


def _startup_parent(instance) -> None:
    _LIFECYCLE_EVENTS.append(f"startup:{instance}")


def _shutdown_parent(instance) -> None:
    _LIFECYCLE_EVENTS.append(f"shutdown:{instance}")


def _build_opt(options: dict, ctx: dict) -> dict:
    """验证扩展点配置段（app.extensions.<name>）透传给 build"""
    return {"options": options, "has_components": "db" in (ctx.get("components") or {})}


def _register_test_extensions() -> None:
    """注册测试专用扩展点（幂等，同名显式覆盖）：依赖对（前置自动启用）与循环依赖对用于装配校验。"""
    ExtensionRegistry.register(
        ExtensionPoint(
            name=TEST_EXT_A,
            build=_build_a,
            startup=_startup_a,
            shutdown=_shutdown_a,
        ),
        overwrite=True,
    )
    ExtensionRegistry.register(
        ExtensionPoint(name=TEST_EXT_PARENT, build=_build_parent, startup=_startup_parent, shutdown=_shutdown_parent),
        overwrite=True,
    )
    ExtensionRegistry.register(
        ExtensionPoint(
            name=TEST_EXT_CHILD,
            requires=(TEST_EXT_PARENT,),
            build=_build_child,
            startup=_startup_child,
            shutdown=_shutdown_child,
        ),
        overwrite=True,
    )
    ExtensionRegistry.register(
        ExtensionPoint(name=TEST_EXT_CYCLE_X, requires=(TEST_EXT_CYCLE_Y,)),
        overwrite=True,
    )
    ExtensionRegistry.register(
        ExtensionPoint(name=TEST_EXT_CYCLE_Y, requires=(TEST_EXT_CYCLE_X,)),
        overwrite=True,
    )
    ExtensionRegistry.register(ExtensionPoint(name=TEST_EXT_OPT, build=_build_opt), overwrite=True)


_register_test_extensions()


# ---------------------------------------------------------------------------
# 注册（同名默认拒绝 / 显式覆盖）
# ---------------------------------------------------------------------------


def test_register_duplicate_rejected():
    """同名注册默认拒绝（避免误覆盖内置/已注册扩展点）"""
    with pytest.raises(ExtensionError):
        ExtensionRegistry.register(ExtensionPoint(name=TEST_EXT_A))


def test_register_duplicate_overwrite_allowed():
    """同名注册显式 overwrite=True 允许覆盖"""
    ExtensionRegistry.register(ExtensionPoint(name=TEST_EXT_B, description="v1"), overwrite=True)
    ExtensionRegistry.register(ExtensionPoint(name=TEST_EXT_B, description="v2"), overwrite=True)
    assert ExtensionRegistry.get(TEST_EXT_B).description == "v2"
    ExtensionRegistry.unregister(TEST_EXT_B)


def test_register_empty_name_raises():
    """扩展点名不能为空"""
    with pytest.raises(ExtensionError):
        ExtensionRegistry.register(ExtensionPoint(name=""))


def test_register_self_dependency_raises():
    """扩展点不能依赖自身"""
    with pytest.raises(ExtensionError):
        ExtensionRegistry.register(ExtensionPoint(name="test_ext_self", requires=("test_ext_self",)))


def test_get_unregister():
    """查询/注销：未注册返回 None，注销后静默"""
    assert ExtensionRegistry.get(TEST_EXT_A) is not None
    assert ExtensionRegistry.get("no_such_extension") is None
    ExtensionRegistry.register(ExtensionPoint(name="test_ext_tmp"), overwrite=True)
    assert "test_ext_tmp" in ExtensionRegistry.names()
    ExtensionRegistry.unregister("test_ext_tmp")
    assert "test_ext_tmp" not in ExtensionRegistry.names()


# ---------------------------------------------------------------------------
# 依赖解析（resolve 拓扑序）
# ---------------------------------------------------------------------------


def test_resolve_includes_prerequisites():
    """解析扩展点自动展开前置：前置在前，目标最后（拓扑序）"""
    resolution = ExtensionRegistry.resolve(TEST_EXT_CHILD)
    assert [cap.name for cap in resolution.chain] == [TEST_EXT_PARENT, TEST_EXT_CHILD]


def test_resolve_single_no_prerequisites():
    """无前置扩展点：解析结果仅目标自身"""
    resolution = ExtensionRegistry.resolve(TEST_EXT_A)
    assert [cap.name for cap in resolution.chain] == [TEST_EXT_A]


def test_resolve_unknown_raises():
    """解析未注册扩展点抛 ExtensionError"""
    with pytest.raises(ExtensionError):
        ExtensionRegistry.resolve("no_such_extension")


def test_resolve_circular_raises():
    """解析依赖循环扩展点抛 ExtensionError"""
    with pytest.raises(ExtensionError):
        ExtensionRegistry.resolve(TEST_EXT_CYCLE_X)


# ---------------------------------------------------------------------------
# 装配校验（validate）
# ---------------------------------------------------------------------------


def test_validate_auto_includes_prerequisites():
    """装配校验：启用子扩展点自动补足前置（缺前置不视为失败，按包含关系展开）"""
    validation = ExtensionRegistry.validate([TEST_EXT_CHILD])
    assert validation.ok
    assert validation.closure == frozenset({TEST_EXT_PARENT, TEST_EXT_CHILD})
    assert validation.chain == (TEST_EXT_PARENT, TEST_EXT_CHILD)
    assert not validation.unknown
    assert not validation.circular


def test_validate_reports_unknown():
    """装配校验：未知扩展点 → ok=False 并给出明细"""
    validation = ExtensionRegistry.validate([TEST_EXT_A, "no_such_extension"])
    assert not validation.ok
    assert "no_such_extension" in validation.unknown
    assert validation.closure == frozenset({TEST_EXT_A})


def test_validate_reports_circular():
    """装配校验：依赖循环 → ok=False 并给出循环链路"""
    validation = ExtensionRegistry.validate([TEST_EXT_CYCLE_X])
    assert not validation.ok
    assert validation.circular


# ---------------------------------------------------------------------------
# create_app 装配钩子（app.extensions.enabled）
# ---------------------------------------------------------------------------


def test_create_app_extensions_build_and_state():
    """create_app 按 app.extensions.enabled 构建扩展点实例并挂 app.state.extensions"""
    app = create_app({"app.extensions.enabled": [TEST_EXT_A]})
    assert app.state.extensions[TEST_EXT_A] == "instance_a"


def test_create_app_extensions_options_passed():
    """扩展点配置段（app.extensions.<name>）透传给 build，装配上下文含已装配组件"""
    app = create_app(
        {
            "app.extensions.enabled": [TEST_EXT_OPT],
            "app.extensions.test_ext_opt": {"key": "value"},
        }
    )
    result = app.state.extensions[TEST_EXT_OPT]
    assert result["options"] == {"key": "value"}
    assert result["has_components"] is True  # build 在组件装配之后执行


def test_create_app_extensions_unknown_raises():
    """create_app 装配校验：未注册扩展点 → ConfigError"""
    with pytest.raises(ConfigError):
        create_app({"app.extensions.enabled": ["no_such_extension"]})


def test_create_app_extensions_circular_raises():
    """create_app 装配校验：依赖循环 → ConfigError"""
    with pytest.raises(ConfigError):
        create_app({"app.extensions.enabled": [TEST_EXT_CYCLE_X]})


# ---------------------------------------------------------------------------
# 生命周期编排（startup 拓扑序 / 停机逆序）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_sync_and_async_hooks():
    """应用启动按拓扑序调用 startup（同步/异步皆可），停机逆序调用 shutdown"""
    _LIFECYCLE_EVENTS.clear()
    app = create_app({"app.extensions.enabled": [TEST_EXT_CHILD]})
    # lifespan_context：进入执行启动段（startup），退出执行停机段（shutdown）
    async with app.router.lifespan_context(app):
        pass
    # build：前置先构建；startup：前置先启动；shutdown：后启先停
    assert _LIFECYCLE_EVENTS == [
        "build:test_ext_parent",
        "build:test_ext_child",
        "startup:parent",
        "startup:child",
        "shutdown:child",
        "shutdown:parent",
    ]


def test_extension_top_level_export():
    """统一扩展注册器随 web_infra 顶层导出（核心机制）"""
    from web_infra import ExtensionRegistry as TopLevelRegistry

    assert TopLevelRegistry is ExtensionRegistry
