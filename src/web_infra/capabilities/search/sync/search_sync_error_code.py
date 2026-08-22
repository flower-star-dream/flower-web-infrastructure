"""
搜索引擎同步错误码

@Author: 花海
@Date: 2026/08/22 15:00
@Description: 搜索引擎同步错误码定义（规范 §4，搜索引擎数据同步方案）：基础设施调用类
              E3-SRCH（可重试：源读取/目标写入失败）、业务状态类 E4-SRCH（配置非法/位点丢失）。
              权威定义见 SearchSyncErrorCodeEnum，SearchSyncErrorCode 类属性引用枚举成员值。
"""
from __future__ import annotations

import logging
from enum import Enum

from web_infra.infra.error.error_code import ErrorCode
from web_infra.infra.error.error_code_registry import ErrorCodeRegistry


class SearchSyncErrorCodeEnum(Enum):
    """搜索引擎同步错误码枚举（E3 可重试 / E4 不可重试）"""

    # E3-SRCH 同步基础设施调用（可重试：源读取中断/目标写入失败）
    CDC_READ_ERROR = ErrorCode(
        "E3-SRCH-010", "CDC 数据源读取失败", 502, "E3", retryable=True, log_level=logging.ERROR
    )
    SYNC_WRITE_ERROR = ErrorCode(
        "E3-SRCH-011", "同步目标写入失败", 502, "E3", retryable=True, log_level=logging.ERROR
    )

    # E4-SRCH 业务状态（不可重试：配置/位点异常）
    SYNC_CONFIG_INVALID = ErrorCode(
        "E4-SRCH-012", "同步配置非法", 422, "E4", log_level=logging.WARNING
    )
    SYNC_OFFSET_LOST = ErrorCode(
        "E4-SRCH-013", "位点无效或丢失", 422, "E4", log_level=logging.WARNING
    )

    @classmethod
    def of(cls, code: str) -> "SearchSyncErrorCodeEnum | None":
        """按 code 反查枚举成员；未找到返回 None"""
        for member in cls:
            if member.value.code == code:
                return member
        return None


class SearchSyncErrorCode:
    """搜索引擎同步错误码（属性引用枚举成员值，对外 API 兼容）"""

    CDC_READ_ERROR = SearchSyncErrorCodeEnum.CDC_READ_ERROR.value
    SYNC_WRITE_ERROR = SearchSyncErrorCodeEnum.SYNC_WRITE_ERROR.value
    SYNC_CONFIG_INVALID = SearchSyncErrorCodeEnum.SYNC_CONFIG_INVALID.value
    SYNC_OFFSET_LOST = SearchSyncErrorCodeEnum.SYNC_OFFSET_LOST.value


def _register_sync_codes() -> None:
    """将搜索引擎同步错误码登记到注册表（模块导入时执行一次）"""
    for member in SearchSyncErrorCodeEnum:
        ErrorCodeRegistry.register(member.value)


_register_sync_codes()
