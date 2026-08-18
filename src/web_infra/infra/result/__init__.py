"""
统一响应结构模块

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一响应结构聚合导出，遵循规范 §4.7（code/message/data）与 §12.3（分页统一 data.list + data.total）。
"""
from web_infra.infra.result.result import Result
from web_infra.infra.result.page_data import PageData
from web_infra.infra.result.page_result import PageResult

__all__ = ["Result", "PageData", "PageResult"]
