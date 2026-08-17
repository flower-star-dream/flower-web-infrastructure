"""
MySQL 连接配置

@Author: 花海
@Date: 2026/08/14 10:00
@Description: MySQL 连接结构化配置（独立字段，避免不同驱动对 URL 查询参数解析差异）。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlparse

from pydantic import BaseModel, Field, SecretStr

from web_infra.constants import INFRA_MYSQL_INIT_COMMAND, INFRA_TRUE_VALUES


class MySQLConnectionSettings(BaseModel):
    """MySQL 连接结构化配置（独立字段，避免不同驱动对 URL 查询参数解析差异）"""

    host: str = Field(default="127.0.0.1", description="MySQL 主机地址")
    port: int = Field(default=3306, description="MySQL 端口")
    database: str = Field(default="", description="数据库名")
    username: str = Field(default="root", description="用户名")
    password: str | SecretStr = Field(default="", description="密码")
    charset: str = Field(default="utf8mb4", description="字符集")
    allow_public_key_retrieval: bool = Field(default=True, description="是否允许从服务器请求 RSA 公钥")
    # SSL/TLS（规范 §10 安全默认：默认开启，可用 usessl=false / use_ssl=false 显式关闭）
    use_ssl: bool = Field(default=True, description="是否使用 SSL/TLS")
    check_hostname: bool = Field(default=True, description="校验服务器证书主机名（仅 use_ssl=True 时生效）")
    ssl_ca: str = Field(default="", description="CA 证书路径（为空时使用系统默认 CA 链）")
    # 超时（规范 §14.1）：连接建立 / 语句执行两层；aiomysql 0.3.x 的 connect()/Connection 均无
    # read_timeout/write_timeout 参数（PyMySQL 同步驱动专属），socket 读写超时在 aiomysql 下不可配置，
    # 故不提供对应字段，防止注入非法参数导致连接失败
    connect_timeout: int = Field(default=10, description="连接建立超时（秒）")
    statement_timeout_seconds: float = Field(default=0.0, description="语句执行超时（秒，0 不启用；>0 时通过会话变量 max_execution_time 生效，仅 SELECT）")
    pool_size: int = Field(default=8, description="连接池大小")
    max_overflow: int = Field(default=8, description="连接池溢出上限")
    pool_recycle: int = Field(default=1800, description="连接回收时间（秒），建议小于 MySQL wait_timeout / 2")
    pool_timeout: int = Field(default=8, description="从连接池获取连接的超时时间（秒）")
    echo: bool = Field(default=False, description="是否打印 SQL 语句")
    pool_pre_ping: bool = Field(default=True, description="借出连接前 ping 检测")
    slow_sql_threshold_seconds: float = Field(default=0.2, description="慢 SQL 告警阈值（秒，P2）")
    slow_sql_critical_seconds: float = Field(default=2.0, description="慢 SQL 严重阈值（秒，P1）")
    leak_detection_threshold_seconds: float = Field(default=10.0, description="连接泄漏检测阈值（秒）")

    def to_sqlalchemy_url(self, driver: str = "aiomysql") -> str:
        """将结构化配置转换为 SQLAlchemy 异步 URL"""
        password = self.password
        if isinstance(password, SecretStr):
            password = password.get_secret_value()
        return f"mysql+{driver}://{self.username}:{password}@{self.host}:{self.port}/{self.database}?charset={self.charset}"

    def _build_init_command(self) -> str:
        """拼接连接初始化命令：UTC 会话时区 + 可选的语句执行超时（规范 §14.1 超时之语句层）"""
        commands = [INFRA_MYSQL_INIT_COMMAND]
        if self.statement_timeout_seconds > 0:
            # MySQL 8.0 会话变量 max_execution_time 仅约束 SELECT，单位毫秒
            commands.append(f"SET SESSION max_execution_time = {int(self.statement_timeout_seconds * 1000)}")
        return "; ".join(commands)

    def to_connect_args(self) -> dict[str, Any]:
        """生成 aiomysql 所需 connect_args（UTC 会话时区、连接建立超时、公钥检索与 SSL）。

        注意：aiomysql 0.3.x 的 connect()/Connection.__init__ 均不接受 read_timeout/write_timeout
        （PyMySQL 同步驱动专属参数），此处不注入，避免 TypeError 导致连接失败。
        """
        connect_args: dict[str, Any] = {
            "server_public_key": self.allow_public_key_retrieval,
            # 每次连接重置会话时区为 UTC（规范 §16.1），并按需设置语句执行超时（规范 §14.1）
            "init_command": self._build_init_command(),
            # aiomysql 参数名为 connect_timeout（timeout 不是其合法参数）
            "connect_timeout": self.connect_timeout,
        }
        if self.use_ssl:
            connect_args["ssl"] = {"ca": self.ssl_ca or None, "check_hostname": self.check_hostname}
        return connect_args

    @classmethod
    def from_url(cls, url: str, username: str | None = None, password: str | None = None) -> "MySQLConnectionSettings":
        """从 SQLAlchemy/JDBC URL 解析为结构化配置，兼容旧配置迁移"""
        parsed = urlparse(url)
        query_params = {k.lower(): v for k, v in parse_qsl(parsed.query)}

        charset = query_params.get("charset", "utf8mb4")
        if charset.lower() == "utf8":
            charset = "utf8mb4"

        allow_public_key_retrieval = (
            query_params.get("allowpublickeyretrieval", "true").lower() in INFRA_TRUE_VALUES
        )
        # 安全默认：URL 未声明 usessl 时默认开启 SSL（与 use_ssl 默认一致）
        use_ssl = query_params.get("usessl", "true").lower() in INFRA_TRUE_VALUES
        check_hostname = query_params.get("checkhostname", "true").lower() in INFRA_TRUE_VALUES

        return cls(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            database=(parsed.path or "").lstrip("/"),
            username=username if username is not None else (parsed.username or ""),
            password=password if password is not None else (parsed.password or ""),
            charset=charset,
            allow_public_key_retrieval=allow_public_key_retrieval,
            use_ssl=use_ssl,
            check_hostname=check_hostname,
        )
