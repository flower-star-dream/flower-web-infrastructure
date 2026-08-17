"""
模型配置来源注册表测试

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 验证（AI 规范 §3.2/§17.4）：
              1) ModelConfigStoreRegistry 类级注册表：内置 yml 条目，自定义来源注册/查询/实例化/注销；
              2) create_app 装配：app.ai.store.type 命中注册表则装配自定义 store 并挂组件，
                 启动生命周期自动同步 SPI 注册表（自定义来源接入点，不锁死 MySQL）；
              3) 未注册的 store.type 启动期快速失败（ConfigError，明确错误提示）。
"""
from __future__ import annotations

import pytest

from web_infra.ai import DictModelConfigStore, ModelConfig, ModelConfigStoreRegistry
from web_infra.application import create_app
from web_infra.config import ConfigError


class _FakeStore(DictModelConfigStore):
    """自定义模型配置来源（仅用于验证注册表装配链路，无实际存储）"""


def _fake_factory(store_name: str):
    """构造按名区分模型清单的自定义 store 工厂"""

    def _factory() -> _FakeStore:
        config = ModelConfig(
            id=0,
            model_code=store_name,
            model_name=store_name,
            provider="openai_compatible",
            api_base="http://mock.test/v1",
            api_key="env:LLM_API_KEY",
        )
        return _FakeStore({store_name: config})

    return _factory


@pytest.fixture
def clean_store_registry():
    """测试后清理全局 store 注册表（保留内置 yml 条目）"""
    before = dict(ModelConfigStoreRegistry._factories)
    yield
    ModelConfigStoreRegistry._factories.clear()
    ModelConfigStoreRegistry._factories.update(before)


def _ai_settings(store_type: str) -> dict:
    """构造启用 AI 且指定模型配置来源的 settings"""
    return {
        "app": {
            "ai": {
                "enabled": True,
                "store": {"type": store_type},
                "models": [],
                "model_gateway": {
                    "default_scene": "chat",
                    "routes": {"chat": {"primary": "m1", "backups": []}},
                },
            }
        }
    }


# ------------------------------------------------------------------
# 注册表基础语义
# ------------------------------------------------------------------


def test_builtin_yml_registered(clean_store_registry):
    """内置 yml 条目导入即注册；create 返回内存/清单实现"""
    assert "yml" in ModelConfigStoreRegistry.registered_names()
    assert isinstance(ModelConfigStoreRegistry.create("yml"), DictModelConfigStore)


def test_register_and_create_custom(clean_store_registry):
    """自定义来源经 register 注册后 create 实例化"""
    ModelConfigStoreRegistry.register("config_center", _fake_factory("m1"))
    store = ModelConfigStoreRegistry.create("config_center")
    assert isinstance(store, _FakeStore)
    assert "m1" in store._configs  # 携带清单

    assert "config_center" in ModelConfigStoreRegistry.registered_names()


def test_register_overwrite(clean_store_registry):
    """同名注册覆盖旧工厂（配置刷新语义）"""
    ModelConfigStoreRegistry.register("cfg", _fake_factory("a"))
    ModelConfigStoreRegistry.register("cfg", _fake_factory("b"))
    store = ModelConfigStoreRegistry.create("cfg")
    assert "b" in store._configs


def test_unregister(clean_store_registry):
    """注销后 get 抛 KeyError（不存在时静默）"""
    ModelConfigStoreRegistry.register("temp", _fake_factory("m1"))
    ModelConfigStoreRegistry.unregister("temp")
    ModelConfigStoreRegistry.unregister("temp")  # 重复注销静默
    with pytest.raises(KeyError):
        ModelConfigStoreRegistry.get("temp")


def test_get_missing_raises_key_error(clean_store_registry):
    """未注册的 store 名 get 抛 KeyError（装配期由 create_app 转 ConfigError）"""
    with pytest.raises(KeyError):
        ModelConfigStoreRegistry.get("not-exist")


# ------------------------------------------------------------------
# create_app 装配
# ------------------------------------------------------------------


def test_unknown_store_type_raises_config_error(clean_store_registry):
    """app.ai.store.type 未注册时启动期快速失败（ConfigError，避免静默回落掩盖配置错误）"""
    with pytest.raises(ConfigError, match="not-exist"):
        create_app(_ai_settings("not-exist"))


def test_create_app_assembles_custom_store(clean_store_registry):
    """自定义来源（SPI 接入点）经注册表装配并挂到组件，不依赖 MySQL"""
    ModelConfigStoreRegistry.register("config_center", _fake_factory("m1"))
    app = create_app(_ai_settings("config_center"))
    assert isinstance(app.state.ai_model_config_store, _FakeStore)


def test_create_app_yml_store_no_component(clean_store_registry):
    """yml 来源不挂 store 组件（模型直接经配置清单注册），注册表校验通过"""
    app = create_app(_ai_settings("yml"))
    assert not hasattr(app.state, "ai_model_config_store")
