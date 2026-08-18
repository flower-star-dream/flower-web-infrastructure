"""
分页查询参数

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 分页查询参数（规范 §12.3：全局统一 pageNo/pageSize）。
              - PageQuery：LIMIT offset 分页，深分页拒绝（规范 S10-1：offset+page_size 超阈值抛错）；
              - 排序参数结构化（规范 §12.2：禁止裸字符串拼接，sort 字段白名单由业务校验）；
              - CursorPageQuery：游标分页（规范 S10-1 推荐方案，对齐规范 §12.3）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from web_infra.infra.constants import (
    PARAM_COMMON_DEFAULT_PAGE_NO,
    PARAM_COMMON_DEFAULT_PAGE_SIZE,
    PARAM_COMMON_MAX_PAGE_SIZE,
)
from web_infra.infra.constants.param_constant import ParamConstant

# 深分页拒绝阈值（规范 S10-1）；constants/__init__.py 尚未重导出，直接经常量类访问
PARAM_COMMON_MAX_OFFSET = ParamConstant.PARAM_COMMON_MAX_OFFSET


class PageQuery(BaseModel):
    """分页查询参数（规范 §12.3：全局统一 pageNo/pageSize；S10-1：拒绝深分页；§12.2：排序结构化）"""

    page_no: int = Field(default=PARAM_COMMON_DEFAULT_PAGE_NO, ge=1, description="页码（从 1 开始）")
    page_size: int = Field(
        default=PARAM_COMMON_DEFAULT_PAGE_SIZE,
        ge=1,
        le=PARAM_COMMON_MAX_PAGE_SIZE,
        description="每页大小",
    )
    # 排序字段名（规范 §12.2：仅结构化传递，禁止裸字符串拼接进 SQL；字段白名单由业务校验）
    sort: str | None = Field(default=None, description="排序字段名（白名单由业务校验，禁止裸字符串拼接，规范 §12.2）")
    # 排序方向（规范 §12.2）：asc/desc，非法值由 pydantic Literal 校验抛错
    order: Literal["asc", "desc"] = Field(default="asc", description="排序方向：asc/desc")

    @model_validator(mode="after")
    def _validate_deep_pagination(self) -> "PageQuery":
        """深分页校验（规范 S10-1：offset+page_size 超过最大偏移阈值时拒绝，建议改用游标分页）"""
        if (self.page_no - 1) * self.page_size + self.page_size > PARAM_COMMON_MAX_OFFSET:
            raise ValueError(
                f"分页偏移超过最大允许值 {PARAM_COMMON_MAX_OFFSET}（page_no*page_size），"
                "深分页已被禁止，请改用游标分页（CursorPageQuery）"
            )
        return self

    @property
    def offset(self) -> int:
        """计算 SQL 分页偏移量"""
        return (self.page_no - 1) * self.page_size

    @property
    def limit(self) -> int:
        """分页大小"""
        return self.page_size

    def order_clause(self) -> tuple[str | None, str]:
        """返回排序子句 (sort, order) 元组，供业务映射为 SQLAlchemy 排序表达式（规范 §12.2）。

        禁止将 sort 直接拼接进 SQL 字符串；排序字段白名单由业务侧校验
        （如 `sort in ALLOWED_SORT_FIELDS`），本方法仅提供结构化入口。
        """
        return self.sort, self.order


class CursorPageQuery(BaseModel):
    """游标分页查询参数（规范 §12.3 / S10-1：禁止 LIMIT offset 深分页，推荐游标分页）。

    使用方式：首页 cursor 传 None，由业务按排序字段生成游标值（如上一页最后一条记录的
    id/时间戳）并返回给前端，后续页携带该游标继续查询；游标比较条件（如
    where_gt: col > :cursor / where_lt: col < :cursor）由业务按需生成。
    """

    cursor: str | None = Field(default=None, description="游标值（上一页最后一条的排序字段值；首页为 None）")
    page_size: int = Field(
        default=PARAM_COMMON_DEFAULT_PAGE_SIZE,
        ge=1,
        le=PARAM_COMMON_MAX_PAGE_SIZE,
        description="每页大小",
    )
