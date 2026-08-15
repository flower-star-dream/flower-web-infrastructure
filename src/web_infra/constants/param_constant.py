"""
参数域常量（PARAM_ 前缀）

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 参数类常量（分页默认值等），对应错误码大类 E1。
              分页默认值为全局唯一权威来源（规范 §12.3），constants/__init__.py 重导出保持一致。
"""
from __future__ import annotations


class ParamConstant:
    """参数域常量类（规范 §5.2 / §5.3）"""

    # 分页默认值（规范 §12.3：全局统一 pageNo/pageSize）
    PARAM_COMMON_DEFAULT_PAGE_NO = 1
    PARAM_COMMON_DEFAULT_PAGE_SIZE = 20
    PARAM_COMMON_MAX_PAGE_SIZE = 500
    # 深分页拒绝阈值（规范 S10-1：禁止 LIMIT offset 深分页，offset+page_size 超阈值直接拒绝，推荐改用游标分页）
    PARAM_COMMON_MAX_OFFSET = 10000

    # 其他参数默认值
    PARAM_COMMON_DEFAULT_PAGE = 1
    PARAM_COMMON_DEFAULT_TOTAL = 0
    PARAM_COMMON_DEFAULT_TOP_N = 20
