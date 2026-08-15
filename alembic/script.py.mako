"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

@Author: 花海
@Date: ${create_date}
@Description: ${message}
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """升级迁移：${upgrades if upgrades else "pass"}"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """回滚迁移：${downgrades if downgrades else "pass"}"""
    ${downgrades if downgrades else "pass"}
