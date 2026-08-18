"""
分页数据结构

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 分页数据结构（规范 §12.3：分页数据统一 data.list + data.total）。
              JSON 键保持为 list（通过 alias 指定），避免与 Python 内建 list 冲突。
"""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# 分页条目类型泛型
T = TypeVar("T")


class PageData(BaseModel, Generic[T]):
    """分页数据结构（规范 §12.3：分页数据统一 data.list + data.total）"""

    model_config = ConfigDict(populate_by_name=True)

    items: list[T] = Field(default_factory=list, alias="list", serialization_alias="list", description="当前页数据列表")
    total: int = Field(default=0, description="总记录数")
