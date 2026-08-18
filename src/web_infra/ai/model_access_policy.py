"""
模型/能力访问权限策略

@Author: 花海
@Date: 2026/08/15
@Description: AI-8 整改：按 RBAC 校验模型/能力使用权限的 SPI 定义与默认实现。
              网关通过可选注入 ModelAccessPolicy 对 chat/stream_chat/embed 入口做权限校验，
              无权限抛 E2-PERM-*；默认 AllowAll 放行（业务注入 RBAC 策略后生效）。
              tenant_id 可选（2026-08-18 评审调整，租户非系统必备）：None/空串表示无租户主体
              （单租户系统），由业务注入的 RBAC 策略自行决定是否校验租户维度。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from web_infra.error import PermException


class ModelAccessPolicy(ABC):
    """模型访问权限策略（SPI）：按模型/租户/用户/场景校验模型与能力使用权限（AI-8）"""

    @abstractmethod
    def check_access(
        self,
        model_name: str,
        tenant_id: str | None,
        user_id: str,
        scene: str | None = None,
    ) -> bool:
        """校验指定模型是否允许当前租户/用户/场景使用。

        :param model_name: 模型逻辑名
        :param tenant_id: 租户标识（可选：None/空串表示无租户主体，单租户系统；策略实现可忽略或按全局放行）
        :param user_id: 用户标识
        :param scene: 调用场景（可选）
        :return: True 允许使用；False 拒绝
        """

    def require_access(
        self,
        model_name: str,
        tenant_id: str | None,
        user_id: str,
        scene: str | None = None,
    ) -> None:
        """权限强校验：check_access 不允许时抛 PermException（E2-PERM-*）。

        :param model_name: 模型逻辑名
        :param tenant_id: 租户标识（可选，语义同 check_access）
        :param user_id: 用户标识
        :param scene: 调用场景（可选）
        :raises PermException: 无权限时抛 E2-PERM-000
        """
        if not self.check_access(model_name, tenant_id, user_id, scene):
            raise PermException(
                message=(
                    f"模型 {model_name} 无使用权限"
                    f"（tenant={tenant_id or '-'}, user={user_id or '-'}, scene={scene or '-'}）"
                )
            )


class AllowAllModelAccessPolicy(ModelAccessPolicy):
    """默认放行策略（AI-8：默认放行，业务注入 RBAC 策略）"""

    def check_access(
        self,
        model_name: str,
        tenant_id: str | None,
        user_id: str,
        scene: str | None = None,
    ) -> bool:
        """恒返回 True：不拦截任何模型调用（保持网关默认行为，业务注入策略后生效）"""
        return True
