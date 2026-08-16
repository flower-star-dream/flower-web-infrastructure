"""
Alembic 迁移 .env 配置加载单元测试

@Author: 花海
@Date: 2026/08/16 10:30
@Description: 验证 alembic/env.py 接入框架 load_env_file 后的数据库 URL 读取链路：
              .env 中的 DATABASE_URL 能被自动加载（迁移命令单独执行时不依赖 shell
              预先导出环境变量），进程/容器环境变量优先（.env 不覆盖），
              缺省 .env 文件时安全兜底不抛异常。
"""
import os

from web_infra.config.config_utils import load_env_file


def _resolve_url() -> str | None:
    """模拟 alembic/env.py _resolve_url() 的数据库 URL 读取链路：load_env_file 后读 DATABASE_URL"""
    return os.environ.get("DATABASE_URL")


def test_load_database_url_from_env_file(tmp_path, monkeypatch):
    """.env 中的 DATABASE_URL 可被自动加载（env.py 迁移链路依赖行为）"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text("DATABASE_URL=sqlite+aiosqlite:///./migration.db\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_env_file() is True
    assert _resolve_url() == "sqlite+aiosqlite:///./migration.db"


def test_existing_env_var_wins_over_env_file(tmp_path, monkeypatch):
    """进程/容器环境变量优先：已存在 DATABASE_URL 时 .env 不覆盖（与框架 override=False 一致）"""
    monkeypatch.setenv("DATABASE_URL", "mysql+aiomysql://root:prod@127.0.0.1:3306/prod_db")
    (tmp_path / ".env").write_text("DATABASE_URL=sqlite+aiosqlite:///./migration.db\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_env_file() is True
    assert _resolve_url() == "mysql+aiomysql://root:prod@127.0.0.1:3306/prod_db"


def test_load_env_file_idempotent(tmp_path, monkeypatch):
    """幂等加载：重复调用不报错（env.py 与应用启动可能先后触发 load_env_file）"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text("DATABASE_URL=sqlite+aiosqlite:///./migration.db\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_env_file() is True
    assert load_env_file() is True
    assert _resolve_url() == "sqlite+aiosqlite:///./migration.db"


def test_missing_env_file_returns_false(tmp_path, monkeypatch):
    """无 .env 文件时安全兜底：返回 False 且不抛异常（迁移仍可走 DATABASE_URL 环境变量）"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    assert load_env_file() is False
