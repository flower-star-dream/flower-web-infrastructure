"""
Alembic 迁移环境配置

@Author: 花海
@Date: 2026/08/15 10:30
@Description: Alembic 迁移环境（整改 S13-1）。支持异步 SQLAlchemy 引擎（mysql+aiomysql /
              sqlite+aiosqlite，项目 MySQL 默认走 aiomysql），同时兼容同步 URL
              （mysql+pymysql / sqlite）。数据库 URL 解析顺序：进程/容器环境变量
              DATABASE_URL > 项目根 .env（自动加载）> alembic.ini 的 sqlalchemy.url
              （ini 中留空），复用框架配置加载能力，避免硬编码数据库连接参数。
"""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path
from typing import Any

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

# 项目 src 目录加入 sys.path（未以 editable 方式安装时也能导入 web_infra 包）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from web_infra.infra.config.config_utils import load_env_file  # noqa: E402  (需在 sys.path 调整后导入)
from web_infra.capabilities.db.mysql_base import Base  # noqa: E402  (需在 sys.path 调整后导入)

# 解析 alembic.ini 中的日志配置
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 声明式模型元数据接入点（autogenerate 依据）：
# 当前框架库未集中定义业务实体模型（Base.metadata 为空）。业务项目需在此处 import
# 其业务模型模块（注册到 Base.metadata），autogenerate 才能对比库表与模型生成迁移。
# 示例（按需取消注释，勿强制 import 不存在的模块）：
#   import business_models  # noqa: F401  (业务模型模块，继承 web_infra.capabilities.db.mysql_base.Base)
target_metadata = Base.metadata


def _resolve_url() -> str:
    """解析迁移数据库 URL：进程/容器环境变量 DATABASE_URL > 项目根 .env（自动加载）> alembic.ini 的 sqlalchemy.url。

    复用框架配置加载能力（web_infra.infra.config.config_utils.load_env_file，与应用启动时
    Settings.default_source() 的 .env 加载行为一致，幂等且不覆盖已存在的环境变量）：
    迁移命令单独执行时同样能消费 .env 中的 DATABASE_URL，避免在 alembic.ini 硬编码数据库连接参数。
    """
    load_env_file()
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url") or ""
    if not url:
        raise RuntimeError(
            "缺少数据库 URL：请设置环境变量 DATABASE_URL（如 sqlite+aiosqlite:///./migration.db），"
            "或配置 alembic.ini [alembic] 段的 sqlalchemy.url"
        )
    return url


def _is_async_url(url: str) -> bool:
    """URL 是否为异步驱动（aiomysql / aiosqlite / asyncpg 等）"""
    return bool(make_url(url).get_dialect().is_async)


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL 脚本不连库（alembic upgrade head --sql）"""
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """在线模式通用迁移执行（异步/同步引擎共用）"""
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """异步引擎迁移入口（sqlite+aiosqlite / mysql+aiomysql 等）"""
    configuration = dict(config.get_section(config.config_ini_section, {}))
    configuration["sqlalchemy.url"] = _resolve_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式：按 URL 驱动类型选择异步或同步引擎"""
    url = _resolve_url()
    if _is_async_url(url):
        asyncio.run(run_async_migrations())
    else:
        connectable: Any = create_engine(url, poolclass=pool.NullPool)
        with connectable.connect() as connection:
            do_run_migrations(connection)
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
