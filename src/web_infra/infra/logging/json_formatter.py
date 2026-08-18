"""
JSON 日志格式化器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: JSON 日志格式化器（便于集中采集与检索，规范 §17.5）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """JSON 日志格式化器（便于集中采集与检索，规范 §17.5）"""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", "-"),
            "phase": getattr(record, "phase", "-"),
            "module": record.module,
            "location": f"{record.filename}.{record.funcName}",
            "user_id": getattr(record, "user_id", "-"),
            # S17-1 错误日志携带完整错误码：业务通过
            # logger.error("...", extra={"error_code": "E2-AUTH-000"}) 传入；
            # 未提供时输出空字符串，保持 JSON 输出结构向后兼容（不破坏既有解析）。
            "error_code": record.__dict__.get("error_code", ""),
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)
