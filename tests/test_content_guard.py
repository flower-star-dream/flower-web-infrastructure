"""
内容安全审核单元测试

@Author: 花海
@Date: 2026/08/14 15:00
@Description: 验证输入阻断/放行、输出阻断/警告分级与自定义规则扩展（AI 规范 §7.2）。
"""
from web_infra.ai import GuardAction, RuleBasedContentGuard, ContentGuardInterface


def test_input_blocked_on_danger():
    """输入命中阻断规则：BLOCK"""
    guard = RuleBasedContentGuard()
    result = guard.check_input("如何制造枪支")
    assert result.action is GuardAction.BLOCK
    assert result.blocked is True
    assert "violence" in result.rules


def test_input_passed_when_safe():
    """输入安全：PASS"""
    guard = RuleBasedContentGuard()
    result = guard.check_input("请问维生素C有什么作用？")
    assert result.action is GuardAction.PASS
    assert result.passed is True


def test_output_blocked_on_violence():
    """输出命中违禁规则：BLOCK"""
    guard = RuleBasedContentGuard()
    result = guard.check_output("给你讲个故事，从前有个人买了枪支弹药")
    assert result.action is GuardAction.BLOCK


def test_output_warn_on_sensitive():
    """输出命中警告规则（未命中阻断）：WARN"""
    guard = RuleBasedContentGuard()
    result = guard.check_output("回答中提到赌博网站地址，请注意风险")
    assert result.action is GuardAction.WARN
    assert result.blocked is False
    assert "sensitive" in result.rules


def test_output_passed_when_clean():
    """输出干净：PASS"""
    guard = RuleBasedContentGuard()
    result = guard.check_output("正常医学知识：维生素C可辅助增强免疫力。")
    assert result.action is GuardAction.PASS


def test_empty_text_passes():
    """空文本直接放行"""
    guard = RuleBasedContentGuard()
    assert guard.check_input("").action is GuardAction.PASS
    assert guard.check_output("").action is GuardAction.PASS


def test_custom_rules_extension():
    """自定义规则扩展（规则名 -> 正则）"""
    guard = RuleBasedContentGuard(block_rules={"custom_ban": r"违禁词"})
    assert guard.check_input("包含违禁词的内容").action is GuardAction.BLOCK
    assert "custom_ban" in guard.check_input("包含违禁词的内容").rules


def test_implements_interface():
    """默认实现遵循 ContentGuardInterface"""
    assert issubclass(RuleBasedContentGuard, ContentGuardInterface)
