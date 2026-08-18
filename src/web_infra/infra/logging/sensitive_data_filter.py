"""
敏感信息脱敏过滤器

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 敏感信息脱敏过滤器：对日志消息统一脱敏（规范 §17.3）。
"""
from __future__ import annotations

import logging

from web_infra.infra.logging.masking import mask


class SensitiveDataFilter(logging.Filter):
    """敏感信息脱敏过滤器：对日志消息统一脱敏（规范 §17.3）"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = mask(record.msg) if isinstance(record.msg, str) else record.msg
            # 参数脱敏：dict（key=value）与位置参数元组（logger.info("phone=%s", phone)）均需覆盖（规范 §17.3）
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: mask(str(v)) for k, v in record.args.items()}
                elif isinstance(record.args, (tuple, list)):
                    record.args = tuple(_mask_arg(v) for v in record.args)
        except Exception:
            # 脱敏失败不应阻断日志输出
            pass
        return True


def _mask_arg(value: object) -> object:
    """位置参数脱敏：文本含敏感信息时打码替换，否则保留原值。

    保留原值可避免破坏日志格式中的类型占位符（如 ``%d`` 期望数值，httpx 等第三方日志依赖）。
    数值参数（int/float/bool）直接跳过脱敏：其字符串表示中的长数字串可能被卡号/证件号正则
    误判（如耗时毫秒 ``2.297104694029847``），导致数值被替换为字符串、``%.3f`` 格式化崩溃。
    """
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    masked = mask(text)
    return masked if masked != text else value
