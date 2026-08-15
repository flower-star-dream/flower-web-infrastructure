"""基线迁移：创建 message_outbox 表

Revision ID: 0001
Revises:
Create Date: 2026/08/15 10:30

@Author: 花海
@Date: 2026/08/15 10:30
@Description: 等价还原 db/init/ddl/001-mq-init-ddl.sql 的 message_outbox 表结构（基线初始形态）。
              注意：磁盘上的基线 SQL 文件当前形态已包含 next_retry_at 列与 idx_status_next_retry
              索引（即"基线初始结构 + V0.2.0 增量"的合流形态）；Alembic 迁移链按历史演进重建：
              本迁移只建基线初始列，next_retry_at 与联合索引由 0002 增量迁移补齐，
              upgrade head 后的表结构与基线 SQL 文件当前形态等价。
              基线 SQL 保留作为参考，Alembic 为权威迁移（规范 §13.1）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级迁移：创建 message_outbox 表（Outbox 本地事务表，规范 §21.3 / 附录 A.13.4）"""
    op.create_table(
        "message_outbox",
        # SQLite 用 INTEGER PRIMARY KEY（rowid 自增别名），MySQL 用 BIGINT AUTO_INCREMENT
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
            primary_key=True,
            comment="主键",
        ),
        sa.Column("msg_id", sa.String(64), nullable=False, comment="消息幂等键组成之一（规范 §9.2）"),
        sa.Column("biz_id", sa.String(64), nullable=False, comment="业务键（幂等键组成之一，如 orderId）"),
        sa.Column("topic", sa.String(128), nullable=False, comment="目标 Topic"),
        sa.Column("tag", sa.String(64), nullable=True, comment="Tag（对齐 §5.8 消息常量规范）"),
        sa.Column("payload", sa.Text(), nullable=False, comment="消息体（JSON）"),
        sa.Column(
            "status",
            sa.SmallInteger().with_variant(mysql.TINYINT(), "mysql"),
            nullable=False,
            server_default=sa.text("0"),
            comment="0 待发送 / 1 已发送 / 2 失败超限 / 3 死信队列",
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="投递重试次数（§9.6）",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间（清理判断依据）"),
        sa.Column("updated_at", sa.DateTime(), nullable=True, comment="最近一次投递/重试时间"),
        sa.Column("cleaned_at", sa.DateTime(), nullable=True, comment="清理时间（§21.3 清理策略）"),
        sa.UniqueConstraint("msg_id", "biz_id", name="uk_msg_biz"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_comment="Outbox 本地事务表",
    )


def downgrade() -> None:
    """回滚迁移：删除 message_outbox 表"""
    op.drop_table("message_outbox")
