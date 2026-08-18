"""
通用配置读取

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一配置抽象与读取实现聚合导出，遵循规范 §15.2 配置安全与附录 A.8。
              应用代码只依赖统一配置抽象接口，按需读取配置中心或本地配置源。
              支持多数据源按优先级组合（环境变量 > 项目 application.yml > 框架默认配置文件），
              配置键采用点分隔（app.cache.type），支持嵌套 JSON/YAML 结构。
              默认配置统一收敛于 application.default.yml（YAML），业务代码与 application 不散落默认值。
"""
from web_infra.infra.config.config_error import ConfigError
from web_infra.infra.config.config_source_interface import ConfigSourceInterface
from web_infra.infra.config.env_config_source import EnvConfigSource
from web_infra.infra.config.dict_config_source import DictConfigSource
from web_infra.infra.config.json_file_config_source import JsonFileConfigSource
from web_infra.infra.config.yaml_config_source import YamlConfigSource
from web_infra.infra.config.composite_config_source import CompositeConfigSource
from web_infra.infra.config.settings import Settings
from web_infra.infra.config.base_config import BaseConfig

__all__ = [
    "ConfigError",
    "ConfigSourceInterface",
    "EnvConfigSource",
    "DictConfigSource",
    "JsonFileConfigSource",
    "YamlConfigSource",
    "CompositeConfigSource",
    "Settings",
    "BaseConfig",
]
