"""
统一响应结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 定义 Web 系统统一响应结构 Result，遵循规范 §4.7（code/message/data）。
              成功 code 固定为 S0000；失败 data 恒为 null。
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from web_infra.constants.sys_constant import SysConstant

# 业务数据类型泛型
T = TypeVar("T")

# 成功码常量（统一管理于 SysConstant，见规范 §4.1）
SUCCESS_CODE = SysConstant.SYS_SUCCESS_CODE
SUCCESS_MESSAGE = SysConstant.SYS_SUCCESS_MESSAGE


class Result(BaseModel, Generic[T]):
    """统一响应结构"""

    code: str = Field(default=SUCCESS_CODE, description="业务错误码（body.code）")
    message: str = Field(default=SUCCESS_MESSAGE, description="可读提示（body.message）")
    data: T | None = Field(default=None, description="业务数据（body.data，失败时为 null）")

    @staticmethod
    def success(data: T | None = None, message: str = SUCCESS_MESSAGE) -> "Result[T]":
        """构造成功响应（code=S0000）"""
        return Result[T](code=SUCCESS_CODE, message=message, data=data)

    @staticmethod
    def failure(code: str, message: str, data: T | None = None) -> "Result[T]":
        """构造失败响应（携带业务错误码，data 默认 null）"""
        return Result[T](code=code, message=message, data=data)
