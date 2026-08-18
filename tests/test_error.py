"""
错误码体系单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证错误码解析、边界收敛与注册表行为（规范 §4）。
"""
import logging

import pytest

from web_infra.infra.error import (
    CommonErrorCode,
    CommonErrorCodeEnum,
    AiErrorCode,
    AiErrorCodeEnum,
    ErrorCodeRegistry,
    BizException,
    parse_category,
    derive_http_status,
    is_client_error,
    is_retryable,
    converge_error_code,
)


def test_parse_category_known_prefixes():
    """解析已知大类前缀"""
    assert parse_category("E1-PARAM-000") == "E1"
    assert parse_category("E2-PERM-000") == "E2"
    assert parse_category("E3-LOCK-000") == "E3"
    assert parse_category("E4-ORDER-001") == "E4"
    assert parse_category("E5-SYS-000") == "E5"
    assert parse_category("S0000") == "S"


def test_parse_category_unknown_prefix_fallback_e5():
    """未知前缀按 E5 兜底（安全失败原则）"""
    assert parse_category("XX-YY-000") == "E5"
    assert parse_category("") == "E5"


def test_error_code_to_exception():
    """错误码 to_exception() 统一异常抛出约定：返回携带相同错误码的 BizException

    业务代码统一 `raise 错误码.to_exception(message=...)` 抛出业务异常，
    避免散落 BizException 构造；message 缺省回落错误码默认文案，data 透传。
    """
    exc = CommonErrorCode.SYS_UNAVAILABLE.to_exception(message="服务不可用（测试）", data={"svc": "demo"})
    assert isinstance(exc, BizException)
    assert exc.code == CommonErrorCode.SYS_UNAVAILABLE.code
    assert exc.http_status == CommonErrorCode.SYS_UNAVAILABLE.http_status
    assert exc.message == "服务不可用（测试）"
    assert exc.data == {"svc": "demo"}
    # 未传 message 时回落错误码默认文案
    assert CommonErrorCode.COMMON_NOT_FOUND.to_exception().message == CommonErrorCode.COMMON_NOT_FOUND.message
    # AI 错误码同样适用（框架内部统一抛出方式）
    assert AiErrorCode.AI_NOT_CONFIGURED.to_exception().code == AiErrorCode.AI_NOT_CONFIGURED.code


def test_derive_http_status():
    """HTTP 状态码按大类推导，子类覆盖（E2-PERM->403，E3-LOCK->423）"""
    assert derive_http_status("E1-PARAM-000") == 400
    assert derive_http_status("E2-AUTH-000") == 401
    assert derive_http_status("E2-PERM-000") == 403
    assert derive_http_status("E3-DB-000") == 500
    assert derive_http_status("E3-LOCK-000") == 423
    assert derive_http_status("E4-ORDER-001") == 422
    assert derive_http_status("E5-SYS-000") == 500


def test_client_error_and_retryable():
    """客户端错误与可重试判定"""
    assert is_client_error("E1") is True
    assert is_client_error("E2") is True
    assert is_client_error("E4") is True
    assert is_client_error("E3") is False
    assert is_client_error("E5") is False
    assert is_retryable("E3") is True
    assert is_retryable("E1") is False


def test_registry_contains_common_codes():
    """通用错误码已登记到注册表"""
    assert ErrorCodeRegistry.get("S0000") is not None
    assert ErrorCodeRegistry.get("E4-COMMON-000") is not None


def test_parse_unknown_code_synthesizes_default():
    """未注册错误码按大类推导默认定义"""
    parsed = ErrorCodeRegistry.parse("E4-ORDER-001")
    assert parsed.category == "E4"
    assert parsed.http_status == 422
    assert parsed.retryable is False


def test_converge_e3_e5():
    """边界收敛：E3/E5 收敛为大类码 + 默认文案"""
    assert converge_error_code("E3-LOCK-000", "锁获取失败") == ("E3", "服务暂时不可用，请稍后重试")
    assert converge_error_code("E5-SYS-000", "未知异常") == ("E5", "系统繁忙，请稍后重试")


def test_converge_pass_categories():
    """边界收敛：E1/E2/E4 透传"""
    assert converge_error_code("E4-ORDER-001", "订单不存在") == ("E4-ORDER-001", "订单不存在")


def test_biz_exception_carries_error_code():
    """业务异常携带错误码与 HTTP 状态"""
    exc = BizException(CommonErrorCode.COMMON_NOT_FOUND)
    assert exc.code == "E4-COMMON-000"
    assert exc.http_status == 404
    assert exc.error_code.log_level == logging.WARNING


# ---------------------------------------------------------------------------
# 错误码枚举化（S4-4）：枚举为权威定义，注册遍历枚举，类属性兼容引用
# ---------------------------------------------------------------------------


def test_enum_contains_all_common_codes():
    """枚举成员覆盖 CommonErrorCode 全部错误码，且与类属性值一致"""
    for member in CommonErrorCodeEnum:
        assert hasattr(CommonErrorCode, member.name), f"枚举成员 {member.name} 缺少对应类属性"
        assert getattr(CommonErrorCode, member.name) is member.value


def test_enum_contains_all_ai_codes():
    """AI 枚举成员覆盖 AiErrorCode 全部错误码，且与类属性值一致"""
    for member in AiErrorCodeEnum:
        assert hasattr(AiErrorCode, member.name), f"枚举成员 {member.name} 缺少对应类属性"
        assert getattr(AiErrorCode, member.name) is member.value


def test_registry_registered_via_enum_traversal():
    """注册表已遍历枚举登记全部错误码（不依赖 dir() 反射）"""
    for member in CommonErrorCodeEnum:
        assert ErrorCodeRegistry.get(member.value.code) is not None, f"通用错误码未注册: {member.value.code}"
    for member in AiErrorCodeEnum:
        assert ErrorCodeRegistry.get(member.value.code) is not None, f"AI 错误码未注册: {member.value.code}"


def test_enum_of_reverse_lookup():
    """枚举 of(code) 反查：已知 code 返回成员，未知 code 返回 None"""
    assert CommonErrorCodeEnum.of("S0000") is CommonErrorCodeEnum.SUCCESS
    assert CommonErrorCodeEnum.of("E2-PERM-000") is CommonErrorCodeEnum.PERM_DENIED
    assert CommonErrorCodeEnum.of("NOT-EXIST-000") is None
    assert AiErrorCodeEnum.of("E3-THIRD-001") is AiErrorCodeEnum.THIRD_UNAVAILABLE
    assert AiErrorCodeEnum.of("E4-AI-999") is None


def test_common_error_code_attrs_unchanged():
    """既有 CommonErrorCode.X.code/message/http_status 引用方式不变（回归保护）"""
    assert CommonErrorCode.SUCCESS.code == "S0000"
    assert CommonErrorCode.SUCCESS.message == "ok"
    assert CommonErrorCode.SUCCESS.http_status == 200
    assert CommonErrorCode.SUCCESS.category == "S"
    assert CommonErrorCode.LOCK_FAILED.code == "E3-LOCK-000"
    assert CommonErrorCode.LOCK_FAILED.http_status == 423
    assert CommonErrorCode.LOCK_FAILED.retryable is True
    assert CommonErrorCode.COMMON_NOT_FOUND.code == "E4-COMMON-000"
    assert CommonErrorCode.COMMON_NOT_FOUND.message == "资源不存在"


def test_ai_error_code_attrs_unchanged():
    """既有 AiErrorCode.X.code/message/http_status 引用方式不变（回归保护）"""
    assert AiErrorCode.AI_NOT_CONFIGURED.code == "E4-AI-001"
    assert AiErrorCode.AI_NOT_CONFIGURED.http_status == 422
    assert AiErrorCode.THIRD_UNAVAILABLE.code == "E3-THIRD-001"
    assert AiErrorCode.THIRD_UNAVAILABLE.retryable is True
