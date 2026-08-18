"""
大整数安全序列化响应

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 统一处理响应中的大整数（雪花 ID），超出 JS 安全整数范围（|v| > 2^53-1）自动转字符串，防止前端精度丢失。
"""
from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

JS_SAFE_INTEGER_MAX = 2**53 - 1
JS_SAFE_INTEGER_MIN = -(2**53 - 1)


def _convert_bigint_fields(value: Any) -> Any:
    """递归将不安全大整数转为字符串"""
    if isinstance(value, int) and not isinstance(value, bool):
        if value > JS_SAFE_INTEGER_MAX or value < JS_SAFE_INTEGER_MIN:
            return str(value)
        return value
    if isinstance(value, dict):
        return {k: _convert_bigint_fields(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert_bigint_fields(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_convert_bigint_fields(v) for v in value)
    if isinstance(value, set):
        return {_convert_bigint_fields(v) for v in value}
    return value


class BigIntJSONResponse(JSONResponse):
    """支持大整数安全序列化的 JSON 响应类"""

    def render(self, content: Any) -> bytes:
        encoded = jsonable_encoder(content)
        safe_content = _convert_bigint_fields(encoded)
        return super().render(safe_content)
