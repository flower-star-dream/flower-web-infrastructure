"""
能力解析结果

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 能力解析（resolve / enable）结果：目标能力 + 按拓扑序展开的依赖链（前置在前）+ 需导入的框架模块清单。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from web_infra.core.capability.capability import Capability


@dataclass(frozen=True)
class CapabilityResolution:
    """能力解析结果：目标能力 + 拓扑序依赖链 + 全部待导入框架模块。

    :param name: 目标能力名
    :param chain: 拓扑序能力链（前置能力在前，目标能力最后，含传递前置）
    :param modules: 需导入的框架模块（前置能力的模块在前，去重保序）
    """

    name: str
    chain: tuple["Capability", ...]
    modules: tuple[str, ...]
