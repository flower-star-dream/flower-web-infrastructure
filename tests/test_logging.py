"""
日志统一格式单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证统一日志入口、文本/JSON 格式配置与敏感信息脱敏（规范 §17 / §17.3）。
"""
import logging

from web_infra.logging import JsonFormatter, SensitiveDataFilter, configure_logging, get_logger
from web_infra.logging.masking import mask


def test_get_logger_prefix():
    """统一日志入口自动加 web_infra 前缀"""
    assert get_logger().name == "web_infra"
    assert get_logger("biz").name == "web_infra.biz"


def test_configure_logging_json():
    """JSON 格式配置生效"""
    configure_logging(level=logging.INFO, fmt="json")
    handler = [h for h in logging.getLogger().handlers if getattr(h, "_web_infra", False)][0]
    assert isinstance(handler.formatter, JsonFormatter)


def test_configure_logging_text():
    """文本格式配置生效"""
    configure_logging(level=logging.INFO, fmt="text")
    handler = [h for h in logging.getLogger().handlers if getattr(h, "_web_infra", False)][0]
    assert isinstance(handler.formatter, logging.Formatter)
    assert not isinstance(handler.formatter, JsonFormatter)


def _make_record(message: str, args) -> logging.LogRecord:
    """构造一条 LogRecord（SensitiveDataFilter 处理用）"""
    return logging.LogRecord("test.logger", logging.INFO, __file__, 1, message, args, None)


def test_sensitive_filter_masks_positional_args():
    """位置参数元组脱敏：logger.info("phone=%s", phone) 不得明文入日志（规范 §17.3）"""
    record = _make_record("phone=%s id=%s", ("13812341234", "110101199001011234"))
    assert SensitiveDataFilter().filter(record) is True
    formatted = record.getMessage()
    assert "13812341234" not in formatted
    assert "110101199001011234" not in formatted
    assert "138****1234" in formatted  # 手机号打码


def test_sensitive_filter_masks_dict_args():
    """dict 参数脱敏：key=value 形式"""
    record = _make_record("login %(username)s", {"username": "admin", "password": "secret123"})
    SensitiveDataFilter().filter(record)
    assert "secret123" not in record.getMessage()


def test_mask_secret_json_quoted_keys():
    """JSON 引号键值脱敏："password": "xxx" 形式（规范 §17.3）"""
    text = '{"username": "admin", "password": "secret123", "api_key": "sk-abc"}'
    masked = mask(text)
    assert "secret123" not in masked
    assert "sk-abc" not in masked


def test_mask_phone_and_card():
    """手机号/身份证/银行卡脱敏"""
    assert mask("13812341234") == "138****1234"
    assert "110101199001011234" not in mask("身份证 110101199001011234")

