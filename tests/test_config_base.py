"""
配置基类单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证 BaseConfig 的 YAML 多环境 profile 加载与占位符解析。
"""
from web_infra.infra.config import BaseConfig


def test_base_config_yaml_profile(tmp_path):
    """YAML 多环境加载：公共配置 + 环境配置深度合并"""
    (tmp_path / "application.yml").write_text("spring:\n  application:\n    name: demo\n", encoding="utf-8")
    (tmp_path / "application-dev.yml").write_text("server:\n  port: 8080\n", encoding="utf-8")

    config = BaseConfig.from_yaml_with_profile(tmp_path, profile="dev")
    assert config.get("spring.application.name") == "demo"
    assert config.get("server.port") == 8080


def test_base_config_env_placeholder(tmp_path, monkeypatch):
    """环境变量占位符解析 ${ENV:default}"""
    monkeypatch.setenv("TEST_DB_HOST", "10.0.0.1")
    (tmp_path / "application.yml").write_text("db:\n  host: ${TEST_DB_HOST:localhost}\n", encoding="utf-8")

    config = BaseConfig.from_yaml_with_profile(tmp_path, profile="default")
    assert config.get("db.host") == "10.0.0.1"
