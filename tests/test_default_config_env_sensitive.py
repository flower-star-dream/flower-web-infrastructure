"""
框架默认配置敏感项环境变量引用单元测试

@Author: 花海
@Date: 2026/08/16 11:00
@Description: 验证框架默认配置 application.default.yml 中敏感项（MySQL/Redis/MongoDB
              账号密码、MinIO/Nacos 访问密钥）经 ${ENV:default} 占位符引用环境变量：
              未设置时回落默认值（密码/密钥为空字符串、username 回落 root），
              设置对应环境变量后优先取环境变量值（敏感配置写入 .env 即可生效）。
"""
import os

from web_infra.infra.config import Settings


def _read(keys: list[str]) -> dict[str, str]:
    """经 Settings 默认配置源批量读取（与应用启动链路一致）"""
    source = Settings.default_source()
    return {key: source.get(key) for key in keys}


def test_default_config_sensitive_fallbacks(tmp_path, monkeypatch):
    """未设置环境变量：敏感项回落默认值（密码/密钥空字符串、username root）"""
    monkeypatch.chdir(tmp_path)
    for name in (
        "APP_DB_MYSQL_USERNAME", "APP_DB_MYSQL_PASSWORD",
        "APP_CACHE_REDIS_USERNAME", "APP_CACHE_REDIS_PASSWORD",
        "APP_MONGO_USERNAME", "APP_MONGO_PASSWORD",
        "APP_STORAGE_MINIO_ACCESS_KEY", "APP_STORAGE_MINIO_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    values = _read(
        [
            "app.db.mysql.username", "app.db.mysql.password",
            "app.cache.redis.username", "app.cache.redis.password",
            "app.mongo.username", "app.mongo.password",
            "app.storage.minio.access_key", "app.storage.minio.secret_key",
        ]
    )
    assert values["app.db.mysql.username"] == "root"
    assert values["app.db.mysql.password"] == ""
    assert values["app.cache.redis.username"] == ""
    assert values["app.cache.redis.password"] == ""
    assert values["app.mongo.username"] == ""
    assert values["app.mongo.password"] == ""
    assert values["app.storage.minio.access_key"] == ""
    assert values["app.storage.minio.secret_key"] == ""


def test_default_config_sensitive_overridden_by_env(tmp_path, monkeypatch):
    """设置环境变量：敏感项优先取环境变量值（.env / 进程环境变量注入即生效，无需改 yml）"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_DB_MYSQL_USERNAME", "db_admin")
    monkeypatch.setenv("APP_DB_MYSQL_PASSWORD", "db_s3cr3t")
    monkeypatch.setenv("APP_CACHE_REDIS_PASSWORD", "redis_s3cr3t")
    monkeypatch.setenv("APP_STORAGE_MINIO_ACCESS_KEY", "minio_ak")
    monkeypatch.setenv("APP_STORAGE_MINIO_SECRET_KEY", "minio_sk")
    monkeypatch.setenv("APP_MONGO_PASSWORD", "mongo_s3cr3t")

    values = _read(
        [
            "app.db.mysql.username", "app.db.mysql.password",
            "app.cache.redis.password",
            "app.storage.minio.access_key", "app.storage.minio.secret_key",
            "app.mongo.password",
        ]
    )
    assert values["app.db.mysql.username"] == "db_admin"
    assert values["app.db.mysql.password"] == "db_s3cr3t"
    assert values["app.cache.redis.password"] == "redis_s3cr3t"
    assert values["app.storage.minio.access_key"] == "minio_ak"
    assert values["app.storage.minio.secret_key"] == "minio_sk"
    assert values["app.mongo.password"] == "mongo_s3cr3t"
