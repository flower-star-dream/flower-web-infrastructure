"""
通用配置单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证 Settings 多数据源读取、优先级与类型转换（规范 §15.2 / 附录 A.8）。
"""
import json

import pytest

from web_infra.config import (
    Settings,
    ConfigError,
    DictConfigSource,
    JsonFileConfigSource,
    CompositeConfigSource,
)


def test_settings_get_from_dict():
    """字典源读取"""
    s = Settings(DictConfigSource({"app.name": "demo"}))
    assert s.get("app.name") == "demo"


def test_settings_type_convert():
    """类型转换：int/bool/list"""
    s = Settings(DictConfigSource({"app.port": "8080", "app.enabled": "true", "app.tags": "a,b,c"}))
    assert s.get_int("app.port") == 8080
    assert s.get_bool("app.enabled") is True
    assert s.get_list("app.tags") == ["a", "b", "c"]


def test_composite_priority():
    """组合源按优先级读取（越靠前越优先）"""
    s = Settings(
        CompositeConfigSource(
            DictConfigSource({"k": "high"}),
            DictConfigSource({"k": "low", "x": "1"}),
        )
    )
    assert s.get("k") == "high"
    assert s.get("x") == "1"


def test_get_required_missing():
    """必填配置缺失抛 ConfigError，并携带缺失的配置键"""
    with pytest.raises(ConfigError) as exc_info:
        Settings(DictConfigSource({})).get_required("missing.key")
    assert exc_info.value.key == "missing.key"


def test_json_file_source(tmp_path):
    """JSON 文件源读取"""
    path = tmp_path / "app.json"
    path.write_text(json.dumps({"a.b": "v"}), encoding="utf-8")
    s = Settings(JsonFileConfigSource(str(path)))
    assert s.get("a.b") == "v"


def test_nested_dict_config():
    """嵌套字典支持点分隔 key 下钻读取"""
    s = Settings(DictConfigSource({"app": {"cache": {"type": "memory"}}}))
    assert s.get("app.cache.type") == "memory"


def test_nested_json_file_config(tmp_path):
    """嵌套 JSON 文件支持点分隔 key 下钻读取"""
    path = tmp_path / "app.json"
    path.write_text(json.dumps({"app": {"db": {"type": "mysql"}}}), encoding="utf-8")
    s = Settings(JsonFileConfigSource(str(path)))
    assert s.get("app.db.type") == "mysql"
