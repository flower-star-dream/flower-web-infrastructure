"""
常量收敛单元测试

@Author: 花海
@Date: 2026/08/15 10:00
@Description: 验证常量收敛（S5-1）：分类常量类为唯一权威来源，constants/__init__.py 仅重导出，
              无同名不同值；分页默认值收敛为实际生效值（PARAM_COMMON_DEFAULT_PAGE_SIZE=20）。
"""
from __future__ import annotations

import sys

import web_infra.constants as constants
from web_infra.constants import (
    AUTH_HEADER_TRACE_ID,
    AUTH_SCOPE_ADMIN,
    AUTH_SCOPE_READ,
    AUTH_SCOPE_WRITE,
    AUTH_TOKEN_ACCESS_EXPIRE_MINUTES,
    INFRA_CALL_MAX_RETRIES,
    INFRA_MYSQL_INIT_COMMAND,
    INFRA_TRUE_VALUES,
    KEY_SEGMENT_SEPARATOR,
    PARAM_COMMON_DEFAULT_PAGE_NO,
    PARAM_COMMON_DEFAULT_PAGE_SIZE,
    PARAM_COMMON_MAX_PAGE_SIZE,
    AuthConstant,
    InfraConstant,
    ParamConstant,
)


def test_page_size_converged_to_single_authoritative_value():
    """分页默认值收敛：__init__.py 重导出与 ParamConstant 权威值一致且等于实际生效值 20"""
    assert ParamConstant.PARAM_COMMON_DEFAULT_PAGE_SIZE == 20
    assert constants.PARAM_COMMON_DEFAULT_PAGE_SIZE == ParamConstant.PARAM_COMMON_DEFAULT_PAGE_SIZE
    # PageQuery 生效默认值（db/page_query.py 从 web_infra.constants 导入）
    from web_infra.db.page_query import PageQuery

    query = PageQuery()
    assert query.page_no == PARAM_COMMON_DEFAULT_PAGE_NO == 1
    assert query.page_size == PARAM_COMMON_DEFAULT_PAGE_SIZE == 20
    assert query.offset == 0
    assert query.limit == 20
    # 上限约束仍为 PARAM_COMMON_MAX_PAGE_SIZE
    assert PageQuery(page_size=PARAM_COMMON_MAX_PAGE_SIZE).page_size == PARAM_COMMON_MAX_PAGE_SIZE


def test_no_same_name_different_value_in_init():
    """重导出常量与分类常量类同值（无同名不同值）"""
    # PARAM_ 域
    assert constants.PARAM_COMMON_DEFAULT_PAGE_NO == ParamConstant.PARAM_COMMON_DEFAULT_PAGE_NO
    assert constants.PARAM_COMMON_DEFAULT_PAGE_SIZE == ParamConstant.PARAM_COMMON_DEFAULT_PAGE_SIZE
    assert constants.PARAM_COMMON_MAX_PAGE_SIZE == ParamConstant.PARAM_COMMON_MAX_PAGE_SIZE
    # AUTH_ 域
    assert constants.AUTH_HEADER_TRACE_ID == AuthConstant.AUTH_HEADER_TRACE_ID == "X-Trace-Id"
    assert constants.AUTH_TOKEN_ACCESS_EXPIRE_MINUTES == AuthConstant.AUTH_TOKEN_ACCESS_EXPIRE_MINUTES == 120
    assert constants.AUTH_SCOPE_READ == AuthConstant.AUTH_SCOPE_READ
    assert constants.AUTH_SCOPE_WRITE == AuthConstant.AUTH_SCOPE_WRITE
    assert constants.AUTH_SCOPE_ADMIN == AuthConstant.AUTH_SCOPE_ADMIN
    # INFRA_ 域
    assert constants.INFRA_MYSQL_INIT_COMMAND == InfraConstant.INFRA_MYSQL_INIT_COMMAND
    assert constants.INFRA_TRUE_VALUES == InfraConstant.INFRA_TRUE_VALUES
    assert constants.INFRA_CALL_MAX_RETRIES == InfraConstant.INFRA_CALL_MAX_RETRIES == 2
    assert constants.KEY_SEGMENT_SEPARATOR == InfraConstant.KEY_SEGMENT_SEPARATOR


def test_infra_true_values_converged():
    """INFRA_TRUE_VALUES 收敛为 tuple 类型，并保留 'on'（原 __init__.py set 行为）"""
    assert isinstance(INFRA_TRUE_VALUES, tuple)
    assert "on" in INFRA_TRUE_VALUES
    # 成员判定行为保持（mysql_config.py / mysql_connection_settings.py 依赖）
    assert "true".lower() in INFRA_TRUE_VALUES
    assert "ON".lower() in INFRA_TRUE_VALUES
    assert "false" not in INFRA_TRUE_VALUES


def test_auth_token_access_ttl_minutes_removed():
    """语义冲突的 AUTH_TOKEN_ACCESS_TTL_MINUTES=15 已移除，统一为 AUTH_TOKEN_ACCESS_EXPIRE_MINUTES=120"""
    assert not hasattr(sys.modules["web_infra.constants"], "AUTH_TOKEN_ACCESS_TTL_MINUTES")
    assert not hasattr(AuthConstant, "AUTH_TOKEN_ACCESS_TTL_MINUTES")
    assert AUTH_TOKEN_ACCESS_EXPIRE_MINUTES == 120


def test_re_exported_names_are_identical_objects():
    """重导出与分类常量类引用同一对象（单一权威来源）"""
    assert AUTH_HEADER_TRACE_ID is AuthConstant.AUTH_HEADER_TRACE_ID
    assert AUTH_SCOPE_ADMIN is AuthConstant.AUTH_SCOPE_ADMIN
    assert INFRA_MYSQL_INIT_COMMAND is InfraConstant.INFRA_MYSQL_INIT_COMMAND
    assert KEY_SEGMENT_SEPARATOR is InfraConstant.KEY_SEGMENT_SEPARATOR
