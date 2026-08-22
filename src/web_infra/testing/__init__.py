"""
框架测试切片基础设施

@Author: 花海
@Date: 2026/08/22 18:00
@Description: 框架级测试切片（对标 Spring Boot Test 切片）：轻量测试上下文装配（只装指定能力子集）、
              组件替身注入（@MockBean 等价）、测试上下文缓存、测试自动回滚。
              供业务项目撰写切片测试，降低单测开销与外部依赖。
"""
from web_infra.testing.test_context import TestContext, web_test_context, bind_test_components
from web_infra.testing.mock_bean import mock_component
from web_infra.testing.fixtures import get_context, clear_cache
from web_infra.testing.rollback import auto_rollback

__all__ = [
    "TestContext",
    "web_test_context",
    "bind_test_components",
    "mock_component",
    "get_context",
    "clear_cache",
    "auto_rollback",
]
