"""
日志规范

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一日志格式、TraceId/用户上下文注入与敏感信息脱敏，遵循规范 §17。
              提供 get_logger 统一入口，支持文本与 JSON 两种格式（JSON 便于集中采集，§17.5）。
              文本格式：[时间] [级别] [TraceId] [阶段] [模块] [类名.方法] [用户ID] 消息内容
"""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

from web_infra.logging.context_filter import ContextFilter
from web_infra.logging.json_formatter import JsonFormatter
from web_infra.logging.sensitive_data_filter import SensitiveDataFilter

# 文本日志格式（规范 §17.2）
TEXT_FORMAT = (
    "[%(asctime)s] [%(levelname)s] [%(trace_id)s] [%(phase)s] "
    "[%(module)s] [%(filename)s.%(funcName)s] [%(user_id)s] %(message)s"
)

_LOGGER_PREFIX = "web_infra"


def get_logger(name: str = _LOGGER_PREFIX) -> logging.Logger:
    """统一日志获取入口：所有业务/框架日志均通过该入口获取，保证格式一致"""
    if not name.startswith(_LOGGER_PREFIX):
        name = f"{_LOGGER_PREFIX}.{name}"
    return logging.getLogger(name)


def configure_logging(
    level: int = logging.INFO,
    fmt: str = "text",
    log_file: str | None = None,
    log_retention_days: int = 30,
) -> None:
    """初始化根日志器：统一注入上下文/脱敏过滤器与格式（幂等，可重复调用）。

    :param level: 根日志级别，默认 INFO
    :param fmt: 输出格式，"text" 或 "json"
    :param log_file: 日志文件路径；提供时额外输出到文件（按天轮转），None 表示仅控制台
    :param log_retention_days: 文件日志保留天数（轮转备份数），默认 30（规范 §17.2 要求 ≥30 天）
    """
    root = logging.getLogger()
    # 清理旧 handler，避免重复添加与格式冲突
    for handler in list(root.handlers):
        if getattr(handler, "_web_infra", False):
            root.removeHandler(handler)

    formatter = JsonFormatter() if fmt == "json" else logging.Formatter(TEXT_FORMAT)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(ContextFilter())
    stream_handler.addFilter(SensitiveDataFilter())
    stream_handler._web_infra = True

    root.setLevel(level)
    root.addHandler(stream_handler)

    if log_file:
        # S17-2 本地文件+日志轮转：按天轮转（midnight），backupCount 控制保留天数
        # （默认 30 天 ≥ 规范要求），utf-8 编码兼容中文日志。
        file_handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            backupCount=log_retention_days,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(ContextFilter())
        file_handler.addFilter(SensitiveDataFilter())
        # 与 StreamHandler 相同的 web_infra 标记，便于 configure_logging 幂等清理；
        # 用 setattr 赋值以规避静态类型检查对动态属性赋值的报错（既有基线的同类写法保留）。
        setattr(file_handler, "_web_infra", True)
        root.addHandler(file_handler)
