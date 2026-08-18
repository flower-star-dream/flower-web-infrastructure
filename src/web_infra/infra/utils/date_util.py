"""
日期时间工具

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一日期时间处理，遵循规范 §16.1（全链路 UTC 存储，DTO 层按用户时区转换）。
              所有业务写入数据库/日志的时间统一使用 DateUtil。
              存储约束（整改 S16-1）：db 连接已通过 constants 包 INFRA_MYSQL_INIT_COMMAND
              强制 `SET time_zone='+00:00'`，与本模块"存储统一 UTC / 展示用配置时区"约定一致：
              入库/落日志使用 utc_now()（固定 UTC，不受 APP_TIMEZONE 影响），
              对外展示按需使用 now()/now_str()（配置时区，可用 with_timezone 输出 ISO Z/偏移）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from web_infra.infra.utils.timezone_config import TimezoneConfig


class DateUtil:
    """日期时间工具类"""

    STANDARD_FORMAT = "%Y-%m-%d %H:%M:%S"
    ISO_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

    @staticmethod
    def now() -> datetime:
        """获取当前配置时区时间（带时区信息，规范 §16.1）。

        注意：存储统一 UTC（与 db 连接 init_command `SET time_zone='+00:00'` 一致，
        落库/落日志请使用 utc_now()/now_utc()），本方法返回配置时区时间，
        仅用于展示层/按用户时区转换场景。
        """
        return datetime.now(TimezoneConfig.get_timezone())

    @staticmethod
    def utc_now() -> datetime:
        """获取当前 UTC 时间（固定 timezone.utc，不受 APP_TIMEZONE 覆盖影响）。

        存储统一 UTC（整改 S16-1）：入库/落日志统一使用本方法，避免时区配置漂移。
        """
        return datetime.now(timezone.utc)

    @staticmethod
    def now_utc() -> datetime:
        """获取当前 UTC 时间（等价 utc_now，向后兼容别名）"""
        return DateUtil.utc_now()

    @staticmethod
    def now_str(fmt: str = STANDARD_FORMAT, with_timezone: bool = False) -> str:
        """获取当前时间字符串。

        :param fmt: 时间格式（默认 %Y-%m-%d %H:%M:%S，不含时区信息）
        :param with_timezone: 是否携带时区信息；True 时输出 ISO 8601（UTC 以 Z 结尾，
            非 UTC 带偏移，如 2026-08-15T10:00:00Z / 2026-08-15T18:00:00+08:00）。
            默认 False 保持原有输出，向后兼容（整改 S16-1）。
        """
        if with_timezone:
            return DateUtil.to_iso_z(DateUtil.now())
        return DateUtil.now().strftime(fmt)

    @staticmethod
    def to_iso_z(dt: datetime) -> str:
        """datetime 转 ISO 8601 字符串（秒精度）：UTC 输出 Z 结尾，非 UTC 输出带偏移。"""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        iso = dt.isoformat(timespec="seconds")
        if iso.endswith("+00:00"):
            return iso[:-6] + "Z"
        return iso

    @staticmethod
    def now_iso() -> str:
        """获取当前时间的 ISO 8601 字符串（带时区偏移）"""
        return DateUtil.now().strftime(DateUtil.ISO_FORMAT)

    @staticmethod
    def timestamp_ms() -> int:
        """获取当前时间戳（毫秒）"""
        return int(DateUtil.now().timestamp() * 1000)

    @staticmethod
    def format(dt: datetime, fmt: str = STANDARD_FORMAT) -> str:
        """格式化日期时间"""
        return dt.strftime(fmt)

    @staticmethod
    def parse(date_str: str, fmt: str = STANDARD_FORMAT) -> datetime:
        """解析日期时间字符串"""
        return datetime.strptime(date_str, fmt)

    @staticmethod
    def to_utc(dt: datetime) -> datetime:
        """将带时区 datetime 转换为 UTC"""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
