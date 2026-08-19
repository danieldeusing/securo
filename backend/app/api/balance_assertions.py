"""Asserted balances — the figure the bank showed, kept beside the one we computed.

Read access follows the workspace's read capability; creating and deleting
require write, the same as any other record that changes what the numbers mean.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.workspace_context import (
    WorkspaceContext,
    current_workspace,
    current_writable_workspace,
)
from app.models.balance_assertion import BalanceAssertion
from app.schemas.balance_assertion import (
    BalanceAssertionCreate,
    BalanceAssertionRead,
    BalanceAssertionReport,
)
from app.services import account_service, balance_assertion_service

router = APIRouter(prefix="/api/balance-assertions", tags=["balance-assertions"])


@router.get("", response_model=list[BalanceAssertionRead])
async def list_assertions(
    account_id: Optional[uuid.UUID] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    query = (
        select(BalanceAssertion)
        .where(BalanceAssertion.workspace_id == ctx.workspace.id)
        .order_by(BalanceAssertion.date.desc())
    )
    if account_id:
        query = query.where(BalanceAssertion.account_id == account_id)
    return (await session.execute(query)).scalars().all()


@router.get("/check", response_model=BalanceAssertionReport)
async def check_assertions(
    account_id: Optional[uuid.UUID] = Query(None),
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Re-check every assertion against the transactions as they stand now.

    Computed on demand rather than stored: a result cached at write time would
    go stale the moment a transaction was imported, edited or deleted, and a
    stale green tick is the one outcome this feature must never produce.
    """
    return await balance_assertion_service.check_workspace(
        session, ctx.workspace.id, account_id
    )


@router.post("", response_model=BalanceAssertionRead, status_code=status.HTTP_201_CREATED)
async def create_assertion(
    data: BalanceAssertionCreate,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    account = await account_service.get_account(session, data.account_id, ctx.workspace.id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    existing = await session.execute(
        select(BalanceAssertion).where(
            BalanceAssertion.account_id == account.id,
            BalanceAssertion.date == data.date,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="This account already has an assertion on that date",
        )

    assertion = await balance_assertion_service.create(
        session, ctx.workspace.id, ctx.user_id, account,
        data.date, data.amount, data.source,
    )
    await session.commit()
    await session.refresh(assertion)
    return assertion


@router.delete("/{assertion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assertion(
    assertion_id: uuid.UUID,
    ctx: WorkspaceContext = Depends(current_writable_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        select(BalanceAssertion).where(
            BalanceAssertion.id == assertion_id,
            BalanceAssertion.workspace_id == ctx.workspace.id,
        )
    )
    assertion = result.scalar_one_or_none()
    if not assertion:
        raise HTTPException(status_code=404, detail="Assertion not found")
    await session.delete(assertion)
    await session.commit()
