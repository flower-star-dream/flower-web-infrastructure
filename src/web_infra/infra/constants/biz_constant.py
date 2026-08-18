"""
业务域常量（BIZ_ 前缀）

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 跨模块共享的业务语义常量，对应错误码大类 E4。业务域常量禁止跨模块直接引用（规范 §5.10）。
"""
from __future__ import annotations


class BizConstant:
    """业务域常量类（规范 §5.2 / §5.10）"""

    # 注：原 BIZ_SSE_MEDIA_TYPE（基础设施媒体类型）已迁移至 InfraConstant.INFRA_SSE_MEDIA_TYPE（规范 §5.7），
    # 本类暂保留空壳以兼容 constants/__init__.py 的既有重导出引用；业务域常量由各业务模块自行定义。
