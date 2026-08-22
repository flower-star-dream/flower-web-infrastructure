"""
日志统一格式与输出通道单元测试

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 验证统一日志入口、文本/JSON 格式配置、敏感信息脱敏（规范 §17 / §17.3），
              以及输出通道配置（both/console/file）与自定义日志通道 SPI（LogSinkInterface / LogSinkRegistry）。
"""
import logging

import pytest

from web_infra.infra.logging import (
    JsonFormatter,
    LogSinkRegistry,
    SensitiveDataFilter,
    configure_logging,
    get_logger,
)
from web_infra.infra.logging.masking import mask


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


# ---------------------------------------------------------------------------
# 输出通道配置（both/console/file）与自定义日志通道 SPI
# ---------------------------------------------------------------------------


def test_configure_logging_output_console_only():
    """output=console：仅控制台 handler，不挂文件"""
    configure_logging(level=logging.INFO, fmt="text", output="console")
    handlers = [h for h in logging.getLogger().handlers if getattr(h, "_web_infra", False)]
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert not isinstance(handlers[0], logging.handlers.TimedRotatingFileHandler)


def test_configure_logging_output_file_only(tmp_path):
    """output=file：仅文件 handler（目录自动创建），不挂控制台"""
    log_file = tmp_path / "logs" / "app.log"
    configure_logging(level=logging.INFO, fmt="text", output="file", log_file=str(log_file))
    handlers = [h for h in logging.getLogger().handlers if getattr(h, "_web_infra", False)]
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.handlers.TimedRotatingFileHandler)
    logging.getLogger("web_infra.test.file_only").info("file only hello")
    assert log_file.exists()
    assert "file only hello" in log_file.read_text(encoding="utf-8")


def test_configure_logging_output_both(tmp_path):
    """output=both：控制台 + 文件同时输出"""
    log_file = tmp_path / "app.log"
    configure_logging(level=logging.INFO, fmt="text", output="both", log_file=str(log_file))
    handlers = [h for h in logging.getLogger().handlers if getattr(h, "_web_infra", False)]
    assert len(handlers) == 2
    assert any(isinstance(h, logging.StreamHandler) for h in handlers)
    assert any(isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in handlers)


def test_configure_logging_output_file_without_log_file_raises():
    """output=file 但未提供 log_file：ValueError 快速失败"""
    with pytest.raises(ValueError):
        configure_logging(level=logging.INFO, fmt="text", output="file")


def test_configure_logging_output_invalid_raises():
    """非法 output：ValueError 快速失败"""
    with pytest.raises(ValueError):
        configure_logging(level=logging.INFO, fmt="text", output="kafka")


class _RecordingHandler(logging.Handler):
    """测试用自定义日志通道 Handler：收集日志记录（不落盘不触网）"""

    def __init__(self, **options):
        super().__init__()
        self.records: list[logging.LogRecord] = []
        for key, value in options.items():
            setattr(self, key, value)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _RecordingLogSink:
    """测试用自定义日志通道（LogSinkInterface SPI 实现）"""

    def create_handler(self, options=None):
        return _RecordingHandler(**(options or {}))


def test_configure_logging_custom_sink_spi():
    """自定义日志通道（SPI）：注册后经 sinks 启用，统一挂载格式器/过滤器，通道配置透传"""
    LogSinkRegistry.register("recording", lambda options: _RecordingLogSink())
    try:
        configure_logging(level=logging.INFO, fmt="text", output="console", sinks={"recording": {"tag": "x"}})
        handlers = [h for h in logging.getLogger().handlers if getattr(h, "_web_infra", False)]
        recording = [h for h in handlers if isinstance(h, _RecordingHandler)]
        assert len(recording) == 1
        assert recording[0].tag == "x"  # app.logging.sinks.<name> 通道配置透传
        logging.getLogger("web_infra.test.sink").info("sink hello")
        assert any("sink hello" in r.getMessage() for r in recording[0].records)
    finally:
        LogSinkRegistry.unregister("recording")


def test_configure_logging_unknown_sink_raises():
    """sinks 中声明未注册通道：ValueError 快速失败"""
    with pytest.raises(ValueError):
        configure_logging(level=logging.INFO, fmt="text", sinks={"no-such-sink": {}})

