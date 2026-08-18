"""
模型配置 API Key 安全测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证 ModelConfig 的 API Key 安全整改（规范 AI-7）：
              ``env:VAR`` 环境变量引用解析、普通值原样返回、缺失环境变量不抛异常并原样返回、
              to_call_kwargs 使用解析后的密钥。
"""
import pytest

from web_infra.capabilities.ai.model_config import ModelConfig


def _config(api_key: str) -> ModelConfig:
    """构造最小模型配置（仅 api_key 可变）"""
    return ModelConfig(
        id=1,
        model_name="Mock Chat",
        model_code="mock-chat",
        provider="openai_compatible",
        api_base="http://mock.test/v1",
        api_key=api_key,
    )


def test_env_ref_resolved_from_environment(monkeypatch):
    """env:VAR 引用从环境变量解析为实际密钥"""
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-from-env")
    config = _config("env:LLM_API_KEY")
    assert config.resolved_api_key == "sk-secret-from-env"
    assert config.get_api_key() == "sk-secret-from-env"


def test_plain_value_returned_as_is():
    """普通明文值（未使用 env: 引用）原样返回"""
    config = _config("sk-plain")
    assert config.resolved_api_key == "sk-plain"


def test_missing_env_var_returns_raw_without_error(monkeypatch):
    """环境变量缺失时原样返回原值且不抛异常"""
    monkeypatch.delenv("NON_EXISTENT_LLM_KEY", raising=False)
    config = _config("env:NON_EXISTENT_LLM_KEY")
    assert config.resolved_api_key == "env:NON_EXISTENT_LLM_KEY"


def test_empty_env_var_value_resolved(monkeypatch):
    """环境变量存在但值为空串时返回空串（变量存在即认为已注入）"""
    monkeypatch.setenv("EMPTY_LLM_KEY", "")
    config = _config("env:EMPTY_LLM_KEY")
    assert config.resolved_api_key == ""


def test_to_call_kwargs_uses_resolved_api_key(monkeypatch):
    """to_call_kwargs 传入解析后的密钥（调用链路不泄露 env: 引用串）"""
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-from-env")
    config = _config("env:LLM_API_KEY")
    assert config.to_call_kwargs()["api_key"] == "sk-secret-from-env"


def test_to_call_kwargs_plain_unchanged():
    """未使用 env: 引用时 to_call_kwargs 行为不变"""
    config = _config("sk-plain")
    assert config.to_call_kwargs()["api_key"] == "sk-plain"


def test_api_key_field_serialization_unchanged():
    """字段名与序列化格式保持不变（不破坏既有配置存储）"""
    config = _config("env:LLM_API_KEY")
    assert config.api_key == "env:LLM_API_KEY"
    assert "api_key" in config.__dict__
    assert "resolved_api_key" not in config.__dict__  # 只读属性不入序列化视图


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("env:THIS_VAR_SHOULD_NOT_EXIST_9f8e7d", "env:THIS_VAR_SHOULD_NOT_EXIST_9f8e7d"),  # 未 setenv 时原样返回
        ("env:", "env:"),  # 空变量名原样返回
    ],
)
def test_env_ref_edge_cases(raw, expected):
    """env: 引用边界场景：缺失变量、空变量名均原样返回"""
    config = _config(raw)
    assert config.resolved_api_key == expected
