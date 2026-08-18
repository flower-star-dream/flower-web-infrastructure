"""
扩展点解析结果

@Author: 花海
@Date: 2026/08/18 14:00
@Description: 扩展点解析结果：按依赖包含规则展开前置扩展点，返回拓扑序扩展点链
              （前置在前，目标最后），供装配与生命周期编排使用。
"""
from __future__ import annotations

from dataclasses import dataclass

from web_infra.extension.extension import ExtensionPoint


@dataclass(frozen=True)
class ExtensionResolution:
    """扩展点解析结果：目标扩展点名与拓扑序扩展点链。

    :param name: 目标扩展点名
    :param chain: 拓扑序扩展点链（前置在前，目标最后）
    """

    name: str
    chain: tuple[ExtensionPoint, ...]
