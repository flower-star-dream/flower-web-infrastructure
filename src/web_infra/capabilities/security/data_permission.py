"""
数据权限守卫

@Author: 花海
@Date: 2026/08/15 14:00
@Description: 数据权限（水平越权）统一组件：按 owner_id 拦截（规范 §25.2）。
              业务在查询/修改资源前调用，防止越权访问他人数据。
"""
from __future__ import annotations

from web_infra.infra.error import PermException


class DataPermissionGuard:
    """数据权限守卫：owner_id 水平越权防护统一组件（规范 §25.2，业务在查询/修改前调用）"""

    @staticmethod
    def check(owner_id: str | None, required_owner_id: str, current_user_id: str) -> None:
        """校验数据属主一致性（规范 §25.2 水平越权防护）。

        任一条件不满足即拒绝，抛 PermException（E2-PERM-000，403）：
        - owner_id 为空（数据属主缺失）→ 拒绝；
        - owner_id != required_owner_id（数据属主与请求声明的属主不一致）→ 拒绝；
        - required_owner_id != current_user_id（请求属主非当前登录用户，越权访问他人数据）→ 拒绝。

        :param owner_id: 数据记录上实际记录的属主标识（可能为 None，表示属主缺失）
        :param required_owner_id: 请求/接口要求的属主标识（如查询参数中的 ownerId）
        :param current_user_id: 当前登录用户标识（取自认证上下文）
        """
        if owner_id is None or owner_id != required_owner_id or required_owner_id != current_user_id:
            raise PermException(message="数据属主校验失败：无权访问该资源")

    @staticmethod
    def is_owner(owner_id: str | None, current_user_id: str) -> bool:
        """便捷判断：数据属主是否为当前登录用户（owner_id 为空视为非属主）"""
        return owner_id is not None and owner_id == current_user_id
