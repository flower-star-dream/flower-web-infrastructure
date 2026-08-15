"""
时区配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 时区配置解析工具，遵循规范 §16.1（全链路 UTC 存储）。
              默认 UTC，可通过环境变量 APP_TIMEZONE 覆盖。
"""
from __future__ import annotations

import os
from datetime import timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo


class TimezoneConfig:
    """时区配置解析工具"""

    DEFAULT_TIMEZONE = "UTC"
    ENV_KEY = "APP_TIMEZONE"

    @staticmethod
    @lru_cache(maxsize=None)
    def get_timezone_name() -> str:
        """获取应用时区名（默认 UTC，规范 §16.1；可通过 APP_TIMEZONE 覆盖）"""
        return os.getenv(TimezoneConfig.ENV_KEY, TimezoneConfig.DEFAULT_TIMEZONE).strip() or TimezoneConfig.DEFAULT_TIMEZONE

    @staticmethod
    @lru_cache(maxsize=None)
    def get_timezone() -> tzinfo:
        """获取时区对象（UTC 直接使用内置 timezone.utc，避免依赖 tzdata）"""
        name = TimezoneConfig.get_timezone_name()
        if name.upper() == "UTC":
            return timezone.utc
        return ZoneInfo(name)
