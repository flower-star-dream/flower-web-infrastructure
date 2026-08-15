"""
分页查询参数单元测试（规范 §12.3 / S10-1）

@Author: 花海
@Date: 2026/08/15 09:00
@Description: 验证 PageQuery 深分页拒绝（S10-1：page_no*page_size 超 10000 抛错）与
              游标分页参数 CursorPageQuery 的默认值与 page_size 上限。
"""
import pytest
from pydantic import ValidationError

from web_infra.constants import (
    PARAM_COMMON_DEFAULT_PAGE_NO,
    PARAM_COMMON_DEFAULT_PAGE_SIZE,
    PARAM_COMMON_MAX_PAGE_SIZE,
)
from web_infra.constants.param_constant import ParamConstant
from web_infra.db.page_query import CursorPageQuery, PageQuery

# 深分页拒绝阈值（规范 S10-1）；constants/__init__.py 尚未重导出，直接经常量类访问
PARAM_COMMON_MAX_OFFSET = ParamConstant.PARAM_COMMON_MAX_OFFSET


def test_page_query_offset():
    """分页参数 offset/limit 计算（pageNo 从 1 开始）"""
    query = PageQuery(page_no=3, page_size=20)
    assert query.offset == 40
    assert query.limit == 20


def test_page_query_deep_pagination_rejected():
    """深分页拒绝：page_no*page_size 超过 10000 抛 ValueError（中文错误消息含最大偏移说明）"""
    with pytest.raises(ValueError, match=f"分页偏移超过最大允许值 {PARAM_COMMON_MAX_OFFSET}"):
        PageQuery(page_no=501, page_size=20)  # 501*20 = 10020 > 10000
    with pytest.raises(ValueError):
        PageQuery(page_no=10001, page_size=1)  # 10001 > 10000
    with pytest.raises(ValueError):
        PageQuery(page_no=200, page_size=60)  # 12000 > 10000


def test_page_query_deep_pagination_boundary():
    """边界：恰好 10000 通过（page_no*page_size == PARAM_COMMON_MAX_OFFSET）"""
    query = PageQuery(page_no=500, page_size=20)
    assert query.offset + query.page_size == PARAM_COMMON_MAX_OFFSET
    assert PageQuery(page_no=10000, page_size=1).offset + 1 == PARAM_COMMON_MAX_OFFSET
    assert PageQuery(page_no=20, page_size=500).offset + 500 == PARAM_COMMON_MAX_OFFSET


def test_page_query_errors_are_validation_errors():
    """深分页拒绝最终表现为 pydantic ValidationError（继承 ValueError），可被框架统一捕获"""
    with pytest.raises(ValidationError):
        PageQuery(page_no=1000, page_size=100)  # 100000 > 10000


def test_cursor_page_query_defaults():
    """游标分页默认值：cursor=None、page_size 复用全局默认值"""
    query = CursorPageQuery()
    assert query.cursor is None
    assert query.page_size == PARAM_COMMON_DEFAULT_PAGE_SIZE


def test_cursor_page_query_values():
    """游标分页显式传值与深分页无偏移限制（游标分页不受 10000 阈值约束）"""
    query = CursorPageQuery(cursor="cursor-abc", page_size=100)
    assert query.cursor == "cursor-abc"
    assert query.page_size == 100


def test_cursor_page_query_max_page_size():
    """游标分页 page_size 上限：超过 PARAM_COMMON_MAX_PAGE_SIZE 抛 ValidationError，恰好等于上限通过"""
    with pytest.raises(ValidationError):
        CursorPageQuery(page_size=PARAM_COMMON_MAX_PAGE_SIZE + 1)
    assert CursorPageQuery(page_size=PARAM_COMMON_MAX_PAGE_SIZE).page_size == PARAM_COMMON_MAX_PAGE_SIZE
    with pytest.raises(ValidationError):
        CursorPageQuery(page_size=0)


def test_page_query_defaults_match_global_constants():
    """PageQuery 默认值与全局常量一致（规范 §12.3：全局统一 pageNo/pageSize）"""
    query = PageQuery()
    assert query.page_no == PARAM_COMMON_DEFAULT_PAGE_NO
    assert query.page_size == PARAM_COMMON_DEFAULT_PAGE_SIZE
