"""
环境显式指定整改单元测试

@Author: 花海
@Date: 2026/08/15
@Description: 验证 S19-3 环境显式指定整改：APP_ENV 环境变量 / 配置 app.env 解析、
              环境变量优先、默认 dev + 告警、非法环境值按 dev 兜底并告警（规范 §19.3）。
"""
import logging

import pytest

from web_infra.infra.config.dict_config_source import DictConfigSource
from web_infra.infra.config.settings import ENVIRONMENTS, Settings


def test_app_env_from_environment_variable(monkeypatch):
    """APP_ENV 环境变量解析（monkeypatch）"""
    monkeypatch.setenv("APP_ENV", "prod")
    s = Settings(DictConfigSource({}))
    assert s.app_env == "prod"
    assert s.is_production() is True


def test_app_env_from_config_when_env_missing(monkeypatch):
    """未设置 APP_ENV 时读取配置 app.env"""
    monkeypatch.delenv("APP_ENV", raising=False)
    s = Settings(DictConfigSource({"app.env": "test"}))
    assert s.app_env == "test"
    assert s.is_production() is False


def test_env_var_priority_over_config(monkeypatch):
    """环境变量优先于配置 app.env"""
    monkeypatch.setenv("APP_ENV", "stage")
    s = Settings(DictConfigSource({"app.env": "dev"}))
    assert s.app_env == "stage"


def test_default_dev_with_warning(monkeypatch, caplog):
    """未显式指定 APP_ENV：默认 dev + warning 日志（规范 §19.3）"""
    monkeypatch.delenv("APP_ENV", raising=False)
    with caplog.at_level(logging.WARNING, logger="web_infra.infra.config.settings"):
        s = Settings(DictConfigSource({}))
    assert s.app_env == "dev"
    assert s.is_production() is False
    assert any("APP_ENV" in r.getMessage() and "dev" in r.getMessage() for r in caplog.records)


def test_invalid_env_falls_back_to_dev_with_warning(monkeypatch, caplog):
    """非法环境值：按 dev 兜底 + warning（文档说明：拒绝抛错或兜底二选一，此处选择兜底）"""
    monkeypatch.setenv("APP_ENV", "local")
    with caplog.at_level(logging.WARNING, logger="web_infra.infra.config.settings"):
        s = Settings(DictConfigSource({}))
    assert s.app_env == "dev"
    assert any("APP_ENV" in r.getMessage() and "非法" in r.getMessage() for r in caplog.records)


def test_env_case_and_whitespace_normalized(monkeypatch):
    """大小写与空白归一化：PROD / " prod " 均解析为 prod"""
    monkeypatch.setenv("APP_ENV", " PROD ")
    s = Settings(DictConfigSource({}))
    assert s.app_env == "prod"
    assert s.is_production() is True


def test_environments_constant():
    """ENVIRONMENTS 合法环境集合（dev/test/stage/prod）"""
    assert ENVIRONMENTS == {"dev", "test", "stage", "prod"}
