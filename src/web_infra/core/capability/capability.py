"""
能力契约

@Author: 花海
@Date: 2026/08/17 16:00
@Description: 能力契约描述：能力名/说明/随能力启用的框架模块/前置能力（按包含关系自动启用）/业务契约。
              框架只负责能力契约（SPI）与依赖包含规则，具体业务实现（如用户系统 user-service）由业务层提供。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    """能力契约：声明能力名称、说明、框架模块、前置能力与业务契约。

    :param name: 能力名（注册表键，如 user / authn / authz / pay）
    :param description: 能力说明
    :param modules: 随能力启用的框架模块（启用时按拓扑序自动导入；业务实现能力为空，如 user）
    :param requires: 前置能力名（按包含关系自动启用，如 pay 前置 authz、authz 前置 authn、authn 前置 user）
    :param contract: 能力契约（SPI / 业务实现要求；业务层据此落地实现）
    """

    name: str
    description: str = ""
    modules: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    contract: str = ""
