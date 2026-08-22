"""
轻量测试上下文

@Author: 花海
@Date: 2026/08/22 18:00
@Description: 轻量测试上下文（对标 @SpringBootTest / @DataJpaTest / @WebMvcTest 切片）：只装配指定
              组件子集，不起全应用（不触网、开销低）。经 web_test_context 构建 TestContext，
              components 指定装配的组件名（如 ("cache",) / ("db",)），按 AOP 组件访问器绑定。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from web_infra.core.aop import bind_components as _bind_aop
from web_infra.infra.config import Settings, CompositeConfigSource, DictConfigSource


@dataclass
class TestContext:
    """测试上下文：轻量组件集合。

    :param components: 已装配组件字典（按 components 子集构建，如 {"cache": MemoryCacheBackend}）
    """

    #: 声明非 pytest 测试类（类名以 Test 开头，避免被 pytest 误收集）
    __test__ = False

    components: dict[str, Any]

    def __getattr__(self, name: str) -> Any:
        """按名取组件（app.state.<name> 语义）"""
        if name in self.components:
            return self.components[name]
        raise AttributeError(f"TestContext 无组件 {name!r}")


def _build_component(name: str, settings: Settings) -> Any:
    """按组件名构建（仅支持无外部依赖的组件子集：cache/mq/storage/registry）。

    :param name: 组件名（"cache"/"mq"/"storage"/"registry"）
    :param settings: 已合并的应用配置（用于读取组件相关参数）
    :return: 对应组件对象
    """
    if name == "cache":
        from web_infra.capabilities.cache import MemoryCacheBackend, CacheConfig

        return MemoryCacheBackend(CacheConfig(max_size=settings.get_int("app.cache.max_size") or 10000))
    if name == "mq":
        from web_infra.capabilities.mq.in_memory_message_queue import InMemoryMessageQueue

        return InMemoryMessageQueue()
    if name == "storage":
        from web_infra.capabilities.storage.local_object_storage import LocalObjectStorage

        return LocalObjectStorage()
    if name == "registry":
        from web_infra.capabilities.registry.in_memory import InMemoryServiceRegistry

        return InMemoryServiceRegistry()
    raise ValueError(f"测试上下文暂不支持组件 {name!r}（内置：cache/mq/storage/registry）")


def web_test_context(settings: dict[str, Any] | None = None, *, components: tuple[str, ...] = ("cache",)) -> TestContext:
    """构建轻量测试上下文（只装配指定组件子集）。

    :param settings: 配置字典（应用配置覆盖）
    :param components: 装配的组件名集合（默认 ("cache",)）
    :return: TestContext（components 已装配并绑定 AOP 访问器）
    """
    merged = CompositeConfigSource(DictConfigSource(settings or {}), Settings.default_source())
    app_settings = Settings(merged)
    components_dict = {name: _build_component(name, app_settings) for name in components}
    _bind_aop(components_dict)
    return TestContext(components_dict)


def bind_test_components(components: dict[str, Any]) -> None:
    """绑定测试组件到 AOP 访问器（供 mock_component 替换）。

    :param components: 组件字典（如 {"cache": ...}）
    """
    _bind_aop(components)
