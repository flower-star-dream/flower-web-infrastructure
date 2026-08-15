"""增量迁移：message_outbox 新增 next_retry_at 列与退避索引

Revision ID: 0002
Revises: 0001
Create Date: 2026/08/15 10:30

@Author: 花海
@Date: 2026/08/15 10:30
@Description: 等价还原 db/versions/V0.2.0-mq-outbox-next-retry-ddl.sql 的语义（S9-4 指数退避）：
              新增 next_retry_at 列（下次可重试时间，NULL 表示无需退避）+ 联合索引
              idx_status_next_retry(status, next_retry_at)。迁移链不承载数据回填，
              存量数据修正 DML 见 db/versions/V0.2.0-mq-outbox-next-retry-dml.sql
              （手工脚本仅供非 Python 环境使用，Alembic 为权威迁移）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级迁移：新增 next_retry_at 列与 idx_status_next_retry 索引"""
    op.add_column(
        "message_outbox",
        sa.Column(
            "next_retry_at",
            sa.DateTime(),
            nullable=True,
            comment="下次可重试时间（指数退避 base*2^retry_count，S9-4；NULL 表示无需退避）",
        ),
    )
    op.create_index("idx_status_next_retry", "message_outbox", ["status", "next_retry_at"])


def downgrade() -> None:
    """回滚迁移：先删索引（依赖列）再删列"""
    op.drop_index("idx_status_next_retry", table_name="message_outbox")
    op.drop_column("message_outbox", "next_retry_at")
