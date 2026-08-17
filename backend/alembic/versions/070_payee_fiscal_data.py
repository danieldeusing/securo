"""enrich payees with contact + fiscal data, and give workspaces a tax jurisdiction

Revision ID: 070
Revises: 069
Create Date: 2026-08-14

Three additive changes, none of them requiring a backfill:

  - Contact and billing columns on `payees`, all nullable. Sync creates a
    payee for every merchant a card touches, and the overwhelming majority
    keep every one of these null forever. That is the expected end state,
    not an incomplete migration.
  - `payee_tax_ids`, one row per fiscal document. Rows rather than columns
    because a counterparty legitimately has several (CNPJ plus state and
    municipal registrations in Brazil, Partita IVA plus Codice Fiscale plus
    an SDI code in Italy), and keyed by `kind` rather than by position so a
    stored value keeps its meaning regardless of which jurisdiction pack was
    loaded when it was written.
  - `workspaces.tax_jurisdiction`, which selects that pack. Nullable, and
    null is a working configuration: the registry falls back to free-text
    documents, so a country without a pack works on day one.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "070"
down_revision: Union[str, None] = "069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payees", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("payees", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("payees", sa.Column("address", sa.String(length=500), nullable=True))
    op.add_column(
        "payees",
        sa.Column("default_payment_terms_days", sa.Integer(), nullable=True),
    )

    op.add_column(
        "workspaces",
        sa.Column("tax_jurisdiction", sa.String(length=10), nullable=True),
    )

    op.create_table(
        "payee_tax_ids",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("value", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["payee_id"], ["payees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # One document of a given kind per payee. A second CNPJ on the same
        # counterparty is a data-entry mistake, not a valid state.
        sa.UniqueConstraint("payee_id", "kind", name="uq_payee_tax_id_kind"),
    )
    op.create_index("ix_payee_tax_ids_payee_id", "payee_tax_ids", ["payee_id"])
    op.create_index("ix_payee_tax_ids_workspace_id", "payee_tax_ids", ["workspace_id"])
    # Matching a payment to a counterparty by document is the lookup this
    # table exists to make cheap.
    op.create_index(
        "ix_payee_tax_ids_workspace_kind_value",
        "payee_tax_ids",
        ["workspace_id", "kind", "value"],
    )


def downgrade() -> None:
    op.drop_index("ix_payee_tax_ids_workspace_kind_value", table_name="payee_tax_ids")
    op.drop_index("ix_payee_tax_ids_workspace_id", table_name="payee_tax_ids")
    op.drop_index("ix_payee_tax_ids_payee_id", table_name="payee_tax_ids")
    op.drop_table("payee_tax_ids")
    op.drop_column("workspaces", "tax_jurisdiction")
    op.drop_column("payees", "default_payment_terms_days")
    op.drop_column("payees", "address")
    op.drop_column("payees", "phone")
    op.drop_column("payees", "email")
