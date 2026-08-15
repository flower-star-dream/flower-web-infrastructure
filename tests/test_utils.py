"""
通用工具单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证日期时间、雪花 ID、数据工具、Token 计算。
"""
import re
from datetime import timezone

from web_infra.utils import (
    DateUtil,
    SnowflakeUtil,
    snowflake_id,
    DataUtil,
    count_tokens,
)


def test_date_util_timestamp_ms():
    """时间戳为正值"""
    assert DateUtil.timestamp_ms() > 0


def test_date_util_utc_now_timezone_is_utc():
    """utc_now 固定返回 UTC 时区（整改 S16-1）"""
    dt = DateUtil.utc_now()
    assert dt.tzinfo == timezone.utc
    assert dt.utcoffset() == timezone.utc.utcoffset(None)


def test_date_util_utc_now_equals_now_utc():
    """utc_now 与向后兼容别名 now_utc 行为一致"""
    assert DateUtil.now_utc().tzinfo == timezone.utc
    assert abs((DateUtil.utc_now() - DateUtil.now_utc()).total_seconds()) < 1


def test_date_util_now_str_default_unchanged():
    """now_str 默认输出不含时区信息（%Y-%m-%d %H:%M:%S，向后兼容）"""
    assert len(DateUtil.now_str()) == 19
    assert DateUtil.now_str().count("-") == 2
    assert "T" not in DateUtil.now_str()


def test_date_util_now_str_with_timezone():
    """now_str(with_timezone=True) 输出 ISO Z 或带偏移（整改 S16-1）"""
    text = DateUtil.now_str(with_timezone=True)
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$")
    assert pattern.match(text) is not None
    assert text.endswith("Z") or "+" in text or "-" in text[19:]


def test_date_util_to_iso_z():
    """to_iso_z：UTC 输出 Z，非 UTC 输出偏移"""
    assert DateUtil.to_iso_z(DateUtil.utc_now()).endswith("Z")


def test_snowflake_unique():
    """雪花 ID 单实例内唯一"""
    util = SnowflakeUtil(worker_id=1)
    ids = {util.next_id() for _ in range(100)}
    assert len(ids) == 100


def test_snowflake_id():
    """便捷函数生成正数 ID"""
    assert snowflake_id() > 0


def test_to_int():
    """安全转整数"""
    assert DataUtil.to_int("123") == 123
    assert DataUtil.to_int("abc", default=-1) == -1


def test_to_float():
    """安全转浮点"""
    assert DataUtil.to_float("3.14") == 3.14
    assert DataUtil.to_float("abc", default=-1.0) == -1.0


def test_to_bool():
    """安全转布尔"""
    assert DataUtil.to_bool("true") is True
    assert DataUtil.to_bool("no") is False
    assert DataUtil.to_bool("unknown", default=True) is True


def test_get_nested():
    """嵌套字典安全取值"""
    data = {"a": {"b": {"c": 1}}}
    assert DataUtil.get_nested(data, "a.b.c") == 1
    assert DataUtil.get_nested(data, "a.x", default=0) == 0


def test_chunk():
    """列表分块"""
    assert DataUtil.chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_unique():
    """列表去重（保持顺序）"""
    assert DataUtil.unique([1, 2, 2, 3, 1]) == [1, 2, 3]


def test_count_tokens():
    """token 计算：空字符串为 0，非空为正"""
    assert count_tokens("") == 0
    assert count_tokens("hello world") > 0
