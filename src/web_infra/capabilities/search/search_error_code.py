"""
搜索引擎错误码

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 搜索引擎错误码定义（规范 §4）：基础设施调用类 E3-SRCH（可重试）、
              业务状态类 E4-SRCH。
              权威定义见 SearchErrorCodeEnum，SearchErrorCode 类属性引用枚举成员值。
"""
from __future__ import annotations

import logging
from enum import Enum

from web_infra.infra.error.error_code import ErrorCode
from web_infra.infra.error.error_code_registry import ErrorCodeRegistry


class SearchErrorCodeEnum(Enum):
    """搜索引擎错误码枚举（规范 §4：基础设施类 E3 可重试 / 业务类 E4 不可重试）"""

    # E3-SRCH 搜索引擎基础设施调用（可重试：网络抖动/ES 集群不可用等）
    SEARCH_ENGINE_ERROR = ErrorCode(
        "E3-SRCH-000", "搜索引擎调用失败", 502, "E3", retryable=True, log_level=logging.ERROR
    )
    SEARCH_INDEX_ERROR = ErrorCode(
        "E3-SRCH-001", "索引操作失败", 502, "E3", retryable=True, log_level=logging.ERROR
    )

    # E4-SRCH 业务状态（不可重试：参数/配置/状态冲突）
    SEARCH_NOT_CONFIGURED = ErrorCode(
        "E4-SRCH-001", "搜索引擎未配置/未注册", 422, "E4", log_level=logging.WARNING
    )
    SEARCH_QUERY_INVALID = ErrorCode(
        "E4-SRCH-002", "检索参数非法", 422, "E4", log_level=logging.WARNING
    )
    SEARCH_INDEX_NOT_FOUND = ErrorCode(
        "E4-SRCH-003", "索引不存在", 404, "E4", log_level=logging.WARNING
    )

    @classmethod
    def of(cls, code: str) -> "SearchErrorCodeEnum | None":
        """按 code 反查枚举成员；未找到返回 None"""
        for member in cls:
            if member.value.code == code:
                return member
        return None


class SearchErrorCode:
    """搜索引擎错误码（属性引用枚举成员值，对外 API 兼容）"""

    SEARCH_ENGINE_ERROR = SearchErrorCodeEnum.SEARCH_ENGINE_ERROR.value
    SEARCH_INDEX_ERROR = SearchErrorCodeEnum.SEARCH_INDEX_ERROR.value
    SEARCH_NOT_CONFIGURED = SearchErrorCodeEnum.SEARCH_NOT_CONFIGURED.value
    SEARCH_QUERY_INVALID = SearchErrorCodeEnum.SEARCH_QUERY_INVALID.value
    SEARCH_INDEX_NOT_FOUND = SearchErrorCodeEnum.SEARCH_INDEX_NOT_FOUND.value


def _register_search_codes() -> None:
    """将搜索引擎错误码登记到注册表（模块导入时执行一次）"""
    for member in SearchErrorCodeEnum:
        ErrorCodeRegistry.register(member.value)


_register_search_codes()
