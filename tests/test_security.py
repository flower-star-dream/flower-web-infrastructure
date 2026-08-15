"""
安全模块单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证密码加密与 PII 脱敏。
"""
from web_infra.security import PasswordEncoder, PrivacyGuard


def test_password_encode_and_verify():
    """密码加密与校验"""
    hashed = PasswordEncoder.encode("secret123")
    assert PasswordEncoder.verify("secret123", hashed)
    assert not PasswordEncoder.verify("wrong", hashed)


def test_privacy_guard_mobile():
    """手机号脱敏"""
    guard = PrivacyGuard()
    assert guard.mask("手机号13812345678") == "手机号138****5678"


def test_privacy_guard_id_card():
    """身份证脱敏"""
    guard = PrivacyGuard()
    result = guard.mask("身份证110101199001011234")
    assert "********" in result


def test_privacy_guard_bank_card():
    """银行卡脱敏"""
    guard = PrivacyGuard()
    assert guard.mask("卡号6222021234567890") == "卡号****7890"
