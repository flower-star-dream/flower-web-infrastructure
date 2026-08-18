"""
日志规范

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一日志格式、TraceId/用户上下文注入与敏感信息脱敏，遵循规范 §17。
              提供 get_logger 统一入口，支持文本与 JSON 两种格式（JSON 便于集中采集，§17.5）。
              文本格式：[时间] [级别] [TraceId] [阶段] [模块] [类名.方法] [用户ID] 消息内容
              日志输出通道可配置（app.logging.output：both/console/file，默认控制台+文件同时输出，
              文件路径与保留天数见 app.logging.file / app.logging.retention_days）；
              自定义存储位置/传输方式经 LogSinkInterface SPI（LogSinkRegistry）注册后，
              在 app.logging.sinks 中声明即启用。
"""
from __future__ import annotations

import logging
from typing import Any

from web_infra.infra.logging.context_filter import ContextFilter
from web_infra.infra.logging.json_formatter import JsonFormatter
from web_infra.infra.logging.log_sink_interface import LogSinkInterface
from web_infra.infra.logging.log_sink_registry import ConsoleLogSink, FileLogSink, LogSinkRegistry
from web_infra.infra.logging.sensitive_data_filter import SensitiveDataFilter

# 文本日志格式（规范 §17.2）
TEXT_FORMAT = (
    "[%(asctime)s] [%(levelname)s] [%(trace_id)s] [%(phase)s] "
    "[%(module)s] [%(filename)s.%(funcName)s] [%(user_id)s] %(message)s"
)

_LOGGER_PREFIX = "web_infra"

__all__ = [
    "TEXT_FORMAT",
    "get_logger",
    "configure_logging",
    "ContextFilter",
    "JsonFormatter",
    "SensitiveDataFilter",
    "LogSinkInterface",
    "LogSinkRegistry",
    "ConsoleLogSink",
    "FileLogSink",
]


def get_logger(name: str = _LOGGER_PREFIX) -> logging.Logger:
    """统一日志获取入口：所有业务/框架日志均通过该入口获取，保证格式一致"""
    if not name.startswith(_LOGGER_PREFIX):
        name = f"{_LOGGER_PREFIX}.{name}"
    return logging.getLogger(name)


def configure_logging(
    level: int = logging.INFO,
    fmt: str = "text",
    *,
    output: str | None = None,
    log_file: str | None = None,
    log_retention_days: int = 30,
    sinks: dict[str, dict[str, Any]] | None = None,
) -> None:
    """初始化根日志器：统一注入上下文/脱敏过滤器与格式（幂等，可重复调用）。

    输出通道由 output 决定（默认控制台 + 文件同时输出，见 app.logging.output 默认值）：
      - "both"：控制台 + 文件同时输出（需 log_file）；
      - "console"：仅控制台；
      - "file"：仅文件（需 log_file）；
      - None：按 log_file 推导（传 log_file 为 both，否则仅控制台，向后兼容旧调用）。
    另可经 sinks 附加自定义日志通道（LogSinkInterface SPI，LogSinkRegistry 按名解析），
    如 output=console 仅保留控制台、sinks 仍按声明启用（多通道并存）。

    :param level: 根日志级别，默认 INFO
    :param fmt: 输出格式，"text" 或 "json"
    :param output: 内置输出通道（both/console/file）；None 表示按 log_file 推导（向后兼容）
    :param log_file: 日志文件路径（output 含 file 时必填；None 表示不输出文件）
    :param log_retention_days: 文件日志保留天数（轮转备份数），默认 30（规范 §17.2 要求 ≥30 天）
    :param sinks: 自定义日志通道（SPI）：name -> 通道配置（options），经 LogSinkRegistry 解析并启用
    :raises ValueError: output 非法、output 含 file 但未提供 log_file、sinks 中通道未注册或通道配置缺失
    """
    root = logging.getLogger()
    # 清理旧 handler，避免重复添加与格式冲突
    for handler in list(root.handlers):
        if getattr(handler, "_web_infra", False):
            root.removeHandler(handler)

    formatter = JsonFormatter() if fmt == "json" else logging.Formatter(TEXT_FORMAT)

    for name in _resolve_output_channels(output, log_file):
        options = {"file": log_file, "retention_days": log_retention_days} if name == "file" else None
        root.addHandler(_build_handler(LogSinkRegistry.create(name, options).create_handler(options), formatter))

    for name, options in (sinks or {}).items():
        try:
            sink = LogSinkRegistry.create(name, options)
        except KeyError:
            raise ValueError(
                f"未注册的日志通道: {name!r}（内置 console/file；自定义通道经 LogSinkRegistry.register 注册）"
            ) from None
        root.addHandler(_build_handler(sink.create_handler(options), formatter))

    root.setLevel(level)


def _resolve_output_channels(output: str | None, log_file: str | None) -> list[str]:
    """解析内置输出通道名列表。

    - output=None（默认）：按 log_file 推导——传 log_file 为 ["console", "file"]（向后兼容），否则 ["console"]；
    - output="both"：["console", "file"]（需 log_file）；
    - output="console"：["console"]；
    - output="file"：["file"]（需 log_file）。

    :param output: 配置的输出通道（both/console/file 或 None）
    :param log_file: 日志文件路径
    :return: 通道名列表（console/file）
    :raises ValueError: output 非法，或 output 含 file 但未提供 log_file
    """
    if output is None:
        return ["console", "file"] if log_file else ["console"]
    if output not in ("console", "file", "both"):
        raise ValueError(f"output 仅支持 console/file/both，当前: {output!r}")
    channels = {"both": ["console", "file"], "console": ["console"], "file": ["file"]}[output]
    if "file" in channels and not log_file:
        raise ValueError("output 含 file 通道时必须提供 log_file（如 configure_logging(log_file=...) 或配置 app.logging.file）")
    return channels


def _build_handler(handler: logging.Handler, formatter: logging.Formatter) -> logging.Handler:
    """统一挂载格式器与上下文/脱敏过滤器，并打 web_infra 标记（供 configure_logging 幂等清理）。

    :param handler: 通道构造的日志 Handler
    :param formatter: 按 fmt 配置的格式器（text/json）
    :return: 挂载完成的 Handler
    """
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter())
    handler.addFilter(SensitiveDataFilter())
    setattr(handler, "_web_infra", True)
    return handler
