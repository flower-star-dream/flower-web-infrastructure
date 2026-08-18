"""
数学工具单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证 MathUtil 的数值处理、统计、向量相似度与转换解析方法。
"""
from decimal import Decimal

import pytest

from web_infra.infra.utils import MathUtil


# ---------------------------------------------------------------------------
# 数值工具
# ---------------------------------------------------------------------------


def test_safe_divide():
    """安全除法：正常相除，除零返回默认值"""
    assert MathUtil.safe_divide(10, 2) == 5.0
    assert MathUtil.safe_divide(1, 0) is None
    assert MathUtil.safe_divide(1, 0, default=-1) == -1


def test_clamp():
    """边界裁剪"""
    assert MathUtil.clamp(5, 0, 10) == 5
    assert MathUtil.clamp(-1, 0, 10) == 0
    assert MathUtil.clamp(11, 0, 10) == 10


def test_round_half_up():
    """常规四舍五入（0.5 向上）"""
    assert MathUtil.round_half_up(1.5) == 2.0
    assert MathUtil.round_half_up(2.675, 2) == 2.68


def test_round_half_even():
    """银行家舍入（0.5 向最近偶数）"""
    assert MathUtil.round_half_even(1.5) == 2.0
    assert MathUtil.round_half_even(2.5) == 2.0
    assert MathUtil.round_half_even(3.5) == 4.0


def test_format_percent():
    """百分比格式化"""
    assert MathUtil.format_percent(0.1234) == "12.34%"
    assert MathUtil.format_percent(0.5, decimals=0) == "50%"


def test_percent():
    """计算占比百分比"""
    assert MathUtil.percent(3, 4) == 75.0


def test_float_eq():
    """浮点近似相等"""
    assert MathUtil.float_eq(0.1 + 0.2, 0.3) is True
    assert MathUtil.float_eq(0.1 + 0.2, 0.3000001) is False


def test_in_range():
    """区间判断"""
    assert MathUtil.in_range(5, 0, 10) is True
    assert MathUtil.in_range(10, 0, 10, include_max=False) is False
    assert MathUtil.in_range(0, 0, 10, include_min=False) is False


# ---------------------------------------------------------------------------
# 统计工具
# ---------------------------------------------------------------------------


def test_mean():
    assert MathUtil.mean([1, 2, 3, 4]) == 2.5


def test_median():
    assert MathUtil.median([1, 3, 2]) == 2
    assert MathUtil.median([1, 2, 3, 4]) == 2.5


def test_mode():
    assert MathUtil.mode([1, 2, 2, 3]) == 2


def test_variance():
    assert MathUtil.variance([1, 2, 3, 4]) == pytest.approx(5 / 3)


def test_std():
    assert MathUtil.std([1, 2, 3, 4]) == pytest.approx((5 / 3) ** 0.5)


def test_percentile():
    assert MathUtil.percentile([1, 2, 3, 4], 50) == 2.5
    assert MathUtil.percentile([1, 2, 3, 4], 100) == 4


def test_moving_average():
    assert MathUtil.moving_average([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]


def test_trim_mean():
    assert MathUtil.trim_mean([1, 100, 2, 3, 4], proportion=0.2) == 3.0


def test_winsorize():
    assert MathUtil.winsorize([1, 2, 3, 100], limits=0.25) == [2, 2, 3, 3]


# ---------------------------------------------------------------------------
# 向量工具
# ---------------------------------------------------------------------------


def test_dot_product():
    assert MathUtil.dot_product([1, 2, 3], [4, 5, 6]) == 32


def test_cosine_similarity():
    assert MathUtil.cosine_similarity([1, 0], [0, 1]) == 0.0
    assert MathUtil.cosine_similarity([1, 0], [1, 0]) == 1.0


def test_euclidean_distance():
    assert MathUtil.euclidean_distance([0, 0], [3, 4]) == 5.0


def test_l2_normalize():
    assert MathUtil.l2_normalize([3, 4]) == pytest.approx([0.6, 0.8])


def test_l1_normalize():
    assert MathUtil.l1_normalize([1, 2, 3]) == pytest.approx([1 / 6, 2 / 6, 3 / 6])


def test_softmax():
    result = MathUtil.softmax([1, 2, 3])
    assert sum(result) == pytest.approx(1.0)
    assert all(0 <= x <= 1 for x in result)


# ---------------------------------------------------------------------------
# 转换与解析
# ---------------------------------------------------------------------------


def test_to_decimal():
    """float 转 Decimal 避免二进制误差"""
    assert MathUtil.to_decimal(0.1) == Decimal("0.1")


def test_parse_int():
    assert MathUtil.parse_int("12.9") == 12
    assert MathUtil.parse_int("abc", default=-1) == -1


def test_parse_float():
    assert MathUtil.parse_float("3.14") == 3.14
    assert MathUtil.parse_float("abc", default=-1.0) == -1.0


def test_percent_decimal_convert():
    assert MathUtil.percent_to_decimal(50) == 0.5
    assert MathUtil.decimal_to_percent(0.5) == 50


def test_int_to_base():
    assert MathUtil.int_to_base(10, 2) == "1010"
    assert MathUtil.int_to_base(255, 16) == "ff"


def test_base_to_int():
    assert MathUtil.base_to_int("1010", 2) == 10
    assert MathUtil.base_to_int("ff", 16) == 255


def test_format_bytes():
    assert MathUtil.format_bytes(0) == "0B"
    assert MathUtil.format_bytes(1024) == "1.00KB"
    assert MathUtil.format_bytes(1536) == "1.50KB"
