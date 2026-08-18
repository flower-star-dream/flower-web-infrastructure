"""
分页统一响应结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 分页统一响应结构 PageResult，遵循规范 §12.3（分页统一 data.list + data.total）。
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from web_infra.infra.result.page_data import PageData
from web_infra.infra.result.result import SUCCESS_CODE, SUCCESS_MESSAGE

# 业务数据类型泛型
T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    """分页统一响应结构"""

    code: str = Field(default=SUCCESS_CODE, description="业务错误码")
    message: str = Field(default=SUCCESS_MESSAGE, description="可读提示")
    data: PageData[T] = Field(default_factory=lambda: PageData[T](), description="分页数据")

    @staticmethod
    def success(records: list[T], total: int, message: str = SUCCESS_MESSAGE) -> "PageResult[T]":
        """构造分页成功响应"""
        return PageResult[T](
            code=SUCCESS_CODE,
            message=message,
            data=PageData[T](list=records, total=total),
        )
