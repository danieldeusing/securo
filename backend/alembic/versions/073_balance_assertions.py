"""add balance assertions

Revision ID: 073
Revises: 072
Create Date: 2026-08-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "073"
down_revision: Union[str, None] = "072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "balance_assertions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("account_id", "date", name="uq_balance_assertion_account_date"),
    )
    op.create_index("ix_balance_assertions_workspace_id", "balance_assertions", ["workspace_id"])
    op.create_index("ix_balance_assertions_account_id", "balance_assertions", ["account_id"])
    op.create_index("ix_balance_assertions_date", "balance_assertions", ["date"])


def downgrade() -> None:
    op.drop_index("ix_balance_assertions_date", table_name="balance_assertions")
    op.drop_index("ix_balance_assertions_account_id", table_name="balance_assertions")
    op.drop_index("ix_balance_assertions_workspace_id", table_name="balance_assertions")
    op.drop_table("balance_assertions")
