"""
SQLAlchemy 声明式基类

@Author: 花海
@Date: 2026/08/14 10:00
@Description: SQLAlchemy 声明式基类，业务实体模型继承此基类（规范 §10 数据访问）。
              依赖解耦（2026-08-15）：Base 惰性导出，未安装 sqlalchemy 的最小安装
              `import web_infra` 不触发导入，首次访问 Base 时才延迟导入。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import declarative_base

# 声明式基类（惰性缓存：首次访问 Base 时导入 sqlalchemy 并创建）
_base: "object | None" = None


def __getattr__(name: str) -> object:
    """惰性导出 Base：首次访问时延迟导入 sqlalchemy（最小安装未装 sqlalchemy 时不触发）

    :param name: 访问的属性名
    :return: 匹配 Base 时返回声明式基类实例
    :raises AttributeError: 未匹配的属性名
    """
    if name == "Base":
        global _base
        if _base is None:
            from sqlalchemy.orm import declarative_base

            _base = declarative_base()
        return _base
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
