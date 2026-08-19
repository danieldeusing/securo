import uuid
from datetime import date as _date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.account import Account


class BalanceAssertion(Base):
    """A statement about what an account HELD, to be checked against what it holds.

    A running balance can tell you what the transactions add up to. It cannot
    tell you a transaction is MISSING — the total is simply lower than reality
    and looks exactly as authoritative as it did the day it was right. That is
    the failure this exists to catch, and it is the common one: a sync gap, a
    statement page nobody imported, an account touched outside the app.

    So an assertion is a second, independent source: the figure the BANK showed
    on a date. Checking is comparing two numbers that were arrived at
    differently, which is the only kind of check worth having.

    Borrowed wholesale from beancount's `balance` directive, including the part
    people get wrong: the amount is what the account held at the START of
    `date`, so an end-of-August statement is asserted on 1 September. That
    convention makes "the closing balance of the last thing before this date"
    expressible without a half-open-interval argument every time.

    IT NEVER CORRECTS ANYTHING. A failing assertion is a question for a person —
    the ledger is wrong, or the assertion is wrong, and software cannot know
    which. An assertion that silently inserted a balancing adjustment would
    destroy the only evidence that something was missed.
    """

    __tablename__ = "balance_assertions"
    __table_args__ = (
        # One statement per account per date. Two different claims about the
        # same moment is not extra information, it is a contradiction, and the
        # database is the cheapest place to refuse it.
        UniqueConstraint("account_id", "date", name="uq_balance_assertion_account_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[_date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(precision=15, scale=2))
    # Denormalised from the account so a later currency change cannot silently
    # reinterpret an assertion that was true in the old one.
    currency: Mapped[str] = mapped_column(String(3))
    # Where the figure came from — "Sparkasse statement 08/2026", "app screen".
    # A failing assertion is investigated by a person, and the first question is
    # always what the number was read off.
    source: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    account: Mapped["Account"] = relationship("Account")
