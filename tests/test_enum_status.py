"""
业务状态枚举统一能力单元测试

@Author: 花海
@Date: 2026/08/15 14:30
@Description: 验证业务状态枚举统一能力（规范 §5.2）：get_code() 返回入库 code（禁存枚举名）、
              of(code) 按值反查成员（未知 code 抛 ValueError）、description 返回中文描述；
              覆盖 8 个枚举：TaskStatus/OutboxStatus/UploadStatus/ChatRole/FinishReason/
              TokenVerifyStatus/CircuitBreakerState/GuardAction。
"""
from __future__ import annotations

from typing import Any

import pytest

from web_infra.ai.chat_role_enum import ChatRole
from web_infra.ai.finish_reason_enum import FinishReason
from web_infra.ai.guard_action import GuardAction
from web_infra.mq.outbox.outbox_status import OutboxStatus
from web_infra.resilience.circuit_breaker_state_enum import CircuitBreakerState
from web_infra.security.token_verify_status_enum import TokenVerifyStatus
from web_infra.storage.upload.upload_status import UploadStatus
from web_infra.task.task_status import TaskStatus

# (枚举类, 一个确定不属于任何成员值的未知 code)
# 8 个枚举无共同基类（IntEnum / str Enum / 普通 Enum），统一以 Any 标注（迭代与成员属性访问均放行）
_ENUM_CASES: list[tuple[Any, int | str]] = [
    (TaskStatus, "NO_SUCH_STATUS"),
    (OutboxStatus, 999),
    (UploadStatus, 999),
    (ChatRole, "NO_SUCH_ROLE"),
    (FinishReason, "NO_SUCH_REASON"),
    (TokenVerifyStatus, "no_such_status"),
    (CircuitBreakerState, "no_such_state"),
    (GuardAction, "NO_SUCH_ACTION"),
]


def test_get_code_matches_member_value():
    """get_code() 返回值与成员值一致（入库存 code）"""
    for enum_cls, _ in _ENUM_CASES:
        for member in enum_cls:
            assert member.get_code() == member.value


def test_of_round_trip():
    """of(合法 code) 反查得到原成员"""
    for enum_cls, _ in _ENUM_CASES:
        for member in enum_cls:
            assert enum_cls.of(member.value) is member


def test_of_unknown_code_raises_value_error():
    """of(未知 code) 抛 ValueError，消息含枚举类名与收到的 code"""
    for enum_cls, unknown in _ENUM_CASES:
        with pytest.raises(ValueError) as exc_info:
            enum_cls.of(unknown)
        assert enum_cls.__name__ in str(exc_info.value)
        assert str(unknown) in str(exc_info.value)


def test_description_non_empty():
    """description 返回非空中文描述（描述表已收录全部成员）"""
    for enum_cls, _ in _ENUM_CASES:
        for member in enum_cls:
            assert member.description, f"{enum_cls.__name__}.{member.name} 描述为空"


def test_specific_get_code_values():
    """关键成员 get_code 断言：TaskStatus.SUCCESS == "SUCCESS"；OutboxStatus.PENDING == 0"""
    assert TaskStatus.SUCCESS.get_code() == "SUCCESS"
    assert OutboxStatus.PENDING.get_code() == 0


def test_task_status_is_terminal_kept():
    """回归：TaskStatus.is_terminal 属性未被破坏（终态判定）"""
    assert TaskStatus.SUCCESS.is_terminal is True
    assert TaskStatus.PENDING.is_terminal is False
