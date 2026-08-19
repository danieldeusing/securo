"""Tests for balance assertions.

An assertion exists to catch the failure that does NOT announce itself: a
transaction that never arrived. The balance is simply lower than reality and
looks exactly as authoritative as it did the day it was right.

So what is tested here is that the check can actually FAIL, and fails for the
right reason. A check that returns ok on everything is indistinguishable from a
correct ledger until the day somebody relies on it.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace
from app.services import balance_assertion_service as svc


async def _account(session: AsyncSession, user: User, workspace: Workspace,
                   currency: str = "EUR") -> Account:
    account = Account(
        id=uuid.uuid4(), user_id=user.id, workspace_id=workspace.id,
        name="Test Checking", type="checking",
        balance=Decimal("0.00"), currency=currency,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def _txn(session: AsyncSession, user: User, workspace: Workspace,
               account: Account, amount: str, txn_type: str, on: date,
               currency: str | None = None, amount_primary: str | None = None):
    txn = Transaction(
        id=uuid.uuid4(), user_id=user.id, workspace_id=workspace.id,
        account_id=account.id, description=f"{txn_type} {amount}",
        amount=Decimal(amount), date=on, effective_date=on,
        type=txn_type, source="manual", status="posted",
        currency=currency or account.currency,
        amount_primary=Decimal(amount_primary) if amount_primary else None,
    )
    session.add(txn)
    await session.commit()
    return txn


@pytest.mark.asyncio
async def test_an_assertion_that_matches_passes(session, test_user, test_workspace):
    account = await _account(session, test_user, test_workspace)
    await _txn(session, test_user, test_workspace, account, "1000.00", "credit", date(2026, 8, 1))
    await _txn(session, test_user, test_workspace, account, "123.45", "debit", date(2026, 8, 10))

    assertion = await svc.create(session, test_workspace.id, test_user.id, account,
                                 date(2026, 9, 1), Decimal("876.55"), "statement 08/2026")
    await session.commit()

    result = await svc.check(session, assertion)
    assert result["actual"] == pytest.approx(876.55)
    assert result["difference"] == 0
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_a_missing_transaction_makes_the_assertion_fail(session, test_user, test_workspace):
    """The whole point. A running balance cannot notice its own gap."""
    account = await _account(session, test_user, test_workspace)
    await _txn(session, test_user, test_workspace, account, "1000.00", "credit", date(2026, 8, 1))
    # The statement says 876,55 — a 123,45 payment we never imported.
    assertion = await svc.create(session, test_workspace.id, test_user.id, account,
                                 date(2026, 9, 1), Decimal("876.55"))
    await session.commit()

    result = await svc.check(session, assertion)
    assert result["ok"] is False
    assert result["difference"] == pytest.approx(123.45)


@pytest.mark.asyncio
async def test_the_assertion_is_the_balance_at_the_START_of_its_date(session, test_user, test_workspace):
    """A transaction ON the date belongs to the next period, not this one.

    Counted inclusively, every assertion fails by exactly one day's activity —
    which reads like a data problem and gets the assertion deleted rather than
    the bug fixed.
    """
    account = await _account(session, test_user, test_workspace)
    await _txn(session, test_user, test_workspace, account, "500.00", "credit", date(2026, 8, 31))
    await _txn(session, test_user, test_workspace, account, "400.00", "credit", date(2026, 9, 1))

    assertion = await svc.create(session, test_workspace.id, test_user.id, account,
                                 date(2026, 9, 1), Decimal("500.00"))
    await session.commit()
    assert (await svc.check(session, assertion))["ok"] is True


@pytest.mark.asyncio
async def test_a_foreign_currency_transaction_contributes_its_converted_amount(
    session, test_user, test_workspace
):
    """The account holds EUR; a BRL charge counts at its amount_primary.

    Taking the raw amount would add 500 BRL to a euro balance as though it were
    500 EUR — a wrong number that still balances, which is the shape of error
    this whole feature exists to surface.
    """
    account = await _account(session, test_user, test_workspace, currency="EUR")
    await _txn(session, test_user, test_workspace, account, "1000.00", "credit", date(2026, 8, 1))
    await _txn(session, test_user, test_workspace, account, "500.00", "debit", date(2026, 8, 5),
               currency="BRL", amount_primary="83.50")

    assertion = await svc.create(session, test_workspace.id, test_user.id, account,
                                 date(2026, 9, 1), Decimal("916.50"))
    await session.commit()
    assert (await svc.check(session, assertion))["ok"] is True


@pytest.mark.asyncio
async def test_a_cent_of_disagreement_still_fails(session, test_user, test_workspace):
    """No tolerance. Small errors are how large ones start."""
    account = await _account(session, test_user, test_workspace)
    await _txn(session, test_user, test_workspace, account, "100.00", "credit", date(2026, 8, 1))
    assertion = await svc.create(session, test_workspace.id, test_user.id, account,
                                 date(2026, 9, 1), Decimal("100.01"))
    await session.commit()

    result = await svc.check(session, assertion)
    assert result["ok"] is False
    assert result["difference"] == pytest.approx(-0.01)


@pytest.mark.asyncio
async def test_the_report_names_the_earliest_failure(session, test_user, test_workspace):
    """Everything after the first break inherits it, so that is where to look."""
    account = await _account(session, test_user, test_workspace)
    await _txn(session, test_user, test_workspace, account, "100.00", "credit", date(2026, 6, 1))

    for on, amount in ((date(2026, 7, 1), "100.00"),
                       (date(2026, 8, 1), "250.00"),
                       (date(2026, 9, 1), "250.00")):
        await svc.create(session, test_workspace.id, test_user.id, account, on, Decimal(amount))
    await session.commit()

    report = await svc.check_workspace(session, test_workspace.id)
    assert report["total"] == 3
    assert report["failing"] == 2
    assert report["earliest_failure"] == "2026-08-01"


@pytest.mark.asyncio
async def test_a_failing_assertion_changes_nothing(session, test_user, test_workspace):
    """It reports. It never repairs.

    A balancing adjustment inserted automatically would destroy the only
    evidence that something was missed, and the books would agree with
    themselves forever after.
    """
    account = await _account(session, test_user, test_workspace)
    await _txn(session, test_user, test_workspace, account, "100.00", "credit", date(2026, 8, 1))
    assertion = await svc.create(session, test_workspace.id, test_user.id, account,
                                 date(2026, 9, 1), Decimal("999.00"))
    await session.commit()

    before = await svc.balance_before(session, account.id, date(2026, 9, 1))
    await svc.check(session, assertion)
    after = await svc.balance_before(session, account.id, date(2026, 9, 1))
    assert before == after == Decimal("100.00")
