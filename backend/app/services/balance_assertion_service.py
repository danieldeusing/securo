"""Checking asserted balances against recorded ones.

The whole value is in WHERE the two numbers come from. One is what somebody
read off a bank statement; the other is what the transactions in this database
add up to. They are arrived at independently, so agreement is evidence and
disagreement is a real finding — usually a transaction that never arrived.

The sum here deliberately reuses the same signed-amount expression
`account_service` uses to compute the balance shown in the UI. Writing a second
one would produce an assertion that can fail while the screen looks right, or
pass while it does not, and either way the check would be worse than useless
because it would be believed.
"""

import uuid
from datetime import date as _date
from decimal import Decimal
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.balance_assertion import BalanceAssertion
from app.models.transaction import Transaction


def _signed_amount():
    """Transaction amount, signed, in the account's own currency.

    Mirrors account_service: `credit` adds, `debit` subtracts, and a transaction
    booked in another currency contributes its `amount_primary` conversion.
    """
    effective = case(
        (Transaction.currency == Account.currency, Transaction.amount),
        else_=func.coalesce(Transaction.amount_primary, Transaction.amount),
    )
    return case((Transaction.type == "credit", effective), else_=-effective)


async def balance_before(session: AsyncSession, account_id: uuid.UUID, on: _date) -> Decimal:
    """What the transactions say the account held at the START of `on`.

    Strictly before, never on. An assertion dated 1 September is about the month
    that ended, so a transaction ON 1 September belongs to the next period and
    must not be counted — get this wrong and every assertion fails by exactly
    one day's activity, which looks like a data problem rather than a bug.
    """
    result = await session.execute(
        select(func.coalesce(func.sum(_signed_amount()), 0))
        .select_from(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .where(Transaction.account_id == account_id, Transaction.date < on)
    )
    return Decimal(str(result.scalar() or 0))


async def check(session: AsyncSession, assertion: BalanceAssertion) -> dict:
    """-> {asserted, actual, difference, ok}. Reports; never repairs."""
    actual = await balance_before(session, assertion.account_id, assertion.date)
    difference = actual - Decimal(assertion.amount)
    return {
        "id": str(assertion.id),
        "account_id": str(assertion.account_id),
        "date": assertion.date.isoformat(),
        "currency": assertion.currency,
        "source": assertion.source,
        "asserted": float(assertion.amount),
        "actual": float(actual),
        "difference": float(difference),
        # Exact equality, to the cent. A tolerance here would be a way of not
        # noticing small errors, and small errors are how large ones start.
        "ok": difference == 0,
    }


async def check_workspace(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    account_id: Optional[uuid.UUID] = None,
) -> dict:
    """Every assertion in the workspace, newest first, with a summary."""
    query = (
        select(BalanceAssertion)
        .where(BalanceAssertion.workspace_id == workspace_id)
        .options(selectinload(BalanceAssertion.account))
        .order_by(BalanceAssertion.date.desc())
    )
    if account_id:
        query = query.where(BalanceAssertion.account_id == account_id)

    assertions = (await session.execute(query)).scalars().all()
    results = []
    for assertion in assertions:
        row = await check(session, assertion)
        row["account_name"] = assertion.account.name if assertion.account else None
        results.append(row)

    failed = [r for r in results if not r["ok"]]
    return {
        "results": results,
        "total": len(results),
        "failing": len(failed),
        # The oldest failure is the one to look at: everything after it inherits
        # the same discrepancy, so fixing the earliest usually clears the rest.
        "earliest_failure": min((r["date"] for r in failed), default=None),
    }


async def create(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    account: Account,
    on: _date,
    amount: Decimal,
    source: Optional[str] = None,
) -> BalanceAssertion:
    assertion = BalanceAssertion(
        workspace_id=workspace_id,
        user_id=user_id,
        account_id=account.id,
        date=on,
        amount=amount,
        currency=account.currency,
        source=source,
    )
    session.add(assertion)
    await session.flush()
    return assertion
