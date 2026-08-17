import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, cast

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.user import User


class Payee(Base):
    __tablename__ = "payees"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(20), default="merchant")
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # Contact and billing details. All nullable and all expected to stay
    # null for the overwhelming majority of rows: sync creates a payee for
    # every merchant a card touches, and none of them need an address.
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # How long this counterparty usually takes to pay, in days. Seeds the
    # due date when an invoice is raised against them.
    default_payment_terms_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Dynamically set by payee_service; not a DB column
    transaction_count = cast(int, 0)

    user: Mapped["User"] = relationship()
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="payee_entity")
    tax_ids: Mapped[list["PayeeTaxId"]] = relationship(
        back_populates="payee", cascade="all, delete-orphan", lazy="selectin"
    )


class PayeeTaxId(Base):
    """One fiscal document belonging to one payee.

    Rows rather than columns, and keyed by `kind` rather than by position.
    A stored value therefore keeps its meaning no matter which jurisdiction
    the workspace is set to or which version of a pack wrote it, and a
    consumer can ask for "this payee's CNPJ" without loading a pack first.

    A counterparty legitimately carries more than one: Brazil wants CNPJ
    plus state and municipal registrations for NFS-e, Italy wants Partita
    IVA plus Codice Fiscale plus an SDI code. Which ones a workspace is
    *offered* comes from `app.fiscal.registry`; which ones it may *store*
    is deliberately unrestricted, because the counterparty's country is not
    the workspace's.
    """

    __tablename__ = "payee_tax_ids"
    __table_args__ = (
        UniqueConstraint("payee_id", "kind", name="uq_payee_tax_id_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payees.id", ondelete="CASCADE"), index=True
    )
    # Derivable from the payee, carried anyway: every financial table in
    # this codebase is directly workspace-scoped, and T6 will filter
    # documents without wanting a join to do it.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    # A value from `fiscal.registry.TaxIdKind`. Stored as a string so a new
    # kind is a pull request and not a database migration, kept closed by
    # validation on the way in.
    kind: Mapped[str] = mapped_column(String(30))
    # Normalised per kind on write: digits only for CPF/CNPJ, upper-cased
    # and stripped of separators for VAT-shaped ids. Formatting for display
    # is the frontend's job, driven by the pack's mask.
    value: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    payee: Mapped["Payee"] = relationship(back_populates="tax_ids")


class PayeeMapping(Base):
    __tablename__ = "payee_mapping"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("payees.id", ondelete="CASCADE"))

    target: Mapped["Payee"] = relationship()
