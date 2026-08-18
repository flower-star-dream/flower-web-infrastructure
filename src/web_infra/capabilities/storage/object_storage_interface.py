"""
对象存储统一抽象接口

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 对象存储统一抽象接口，屏蔽 MinIO/云 OSS/S3 差异（规范 §22）。
              下载/删除支持可插拔属主校验钩子（规范 §22.4：防止水平越权下载）。
"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

# 属主校验器签名（规范 §22.4）：object_id(对象 key) / owner(文件属主) / current_user(当前登录用户，
# 由实现层从请求上下文获取后传入)；校验失败应抛出权限异常（如 PermException，E2-PERM-*）
OwnerValidator = Callable[[str, str | None, str | None], None]


@runtime_checkable
class ObjectStorageInterface(Protocol):
    """对象存储统一抽象接口"""

    async def put(self, bucket: str, key: str, data: bytes, content_type: str | None = None) -> None:
        """上传对象"""
        ...

    async def get(
        self,
        bucket: str,
        key: str,
        *,
        owner: str | None = None,
        owner_validator: OwnerValidator | None = None,
    ) -> bytes | None:
        """下载对象，不存在返回 None。

        :param owner: 文件属主标识（规范 §22.4 属主校验，防水平越权下载；缺省 None 不校验）
        :param owner_validator: 可插拔属主校验钩子 (object_id, owner, current_user)，由业务注入
            （如配合 DataPermissionGuard 按 owner_id 拦截）；缺省 None 不校验
        """
        ...

    async def delete(
        self,
        bucket: str,
        key: str,
        *,
        owner: str | None = None,
        owner_validator: OwnerValidator | None = None,
    ) -> None:
        """删除对象（owner/owner_validator 语义与 get 一致，规范 §22.4 防越权删除）"""
        ...

    async def exists(self, bucket: str, key: str) -> bool:
        """判断对象是否存在"""
        ...

    async def presign_url(self, bucket: str, key: str, expires: int | None = None) -> str:
        """生成带过期时间的访问 URL（真实对象存储为签名 URL，规范 §22.3）"""
        ...
