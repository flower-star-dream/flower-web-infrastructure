"""
搜索引擎检索参数

@Author: 花海
@Date: 2026/08/18 10:00
@Description: 全文搜索引擎检索参数模型（搜索引擎接入计划 v0.2.0 §3.2）：
              关键词 / 目标索引 / 分页（offset/size）/ 高亮开关。
              分页与高亮为可选参数，缺省回落框架默认（见 SearchConstant）。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from web_infra.search.search_constant import SearchConstant


class SearchQuery(BaseModel):
    """搜索引擎检索参数"""

    keyword: str = Field(min_length=1, description="查询关键词（必填，长度 ≥1）")
    index_name: str = Field(default=SearchConstant.DEFAULT_INDEX_NAME, description="业务索引名（在租户命名空间内解析）")
    offset: int = Field(default=0, ge=0, description="分页偏移（对应 ES from，默认 0）")
    size: int = Field(
        default=SearchConstant.DEFAULT_PAGE_SIZE,
        ge=1,
        le=SearchConstant.MAX_PAGE_SIZE,
        description="返回条数（对应 ES size，1~100，默认 10）",
    )
    highlight: bool = Field(default=False, description="是否返回高亮片段（默认关闭）")
