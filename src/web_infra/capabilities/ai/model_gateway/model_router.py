"""
模型路由器

@Author: 花海
@Date: 2026/08/14 16:00
@Description: 场景模型路由（AI 规范 §2.3：按场景配置模型路由规则，模型网关统一决策）：
              未配置场景时回退默认场景；均未命中抛 E4-AI-001（模型/供应商未配置）。
"""
from __future__ import annotations

from web_infra.capabilities.ai.model_gateway.model_gateway_config import RouteEntry
from web_infra.infra.error.ai_error_code import AiErrorCode


class ModelRouter:
    """场景 -> 模型路由（主备降级）"""

    def __init__(self, routes: dict[str, RouteEntry], default_scene: str = "") -> None:
        """初始化路由器。

        :param routes: 场景 -> 路由条目 映射
        :param default_scene: 默认场景（无匹配时回退；空则抛 E4-AI-001）
        """
        self._routes = dict(routes)
        self._default_scene = default_scene

    def route(self, scene: str) -> RouteEntry:
        """按场景解析路由条目。

        :param scene: 调用场景
        :return: 路由条目（主备模型）
        :raises BizException: 场景未配置且无默认场景时抛 E4-AI-001
        """
        entry = self._routes.get(scene)
        if entry is None and self._default_scene:
            entry = self._routes.get(self._default_scene)
        if entry is None:
            raise AiErrorCode.AI_NOT_CONFIGURED.to_exception(message=f"场景 {scene} 未配置模型路由")
        return entry
