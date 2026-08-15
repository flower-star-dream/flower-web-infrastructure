"""
配置错误异常

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 配置缺失或类型错误时抛出的异常。
              携带缺失/错误的配置键，便于调用方定位具体是哪一个配置项出了问题。
"""
from __future__ import annotations


class ConfigError(RuntimeError):
    """配置缺失或类型错误时抛出的异常"""

    def __init__(self, message: str, key: str | None = None) -> None:
        """初始化配置异常。

        :param message: 异常描述信息
        :param key: 缺失或错误的配置键（点分隔，如 app.db.mysql.host），便于定位问题配置项
        """
        self.key = key
        super().__init__(message)
