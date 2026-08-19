import uuid
from datetime import date as _date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BalanceAssertionCreate(BaseModel):
    account_id: uuid.UUID
    # The balance held at the START of this date — an end-of-August statement is
    # asserted on 1 September. See the model docstring.
    date: _date
    amount: Decimal
    source: Optional[str] = Field(default=None, max_length=255)


class BalanceAssertionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    date: _date
    amount: Decimal
    currency: str
    source: Optional[str] = None


class BalanceAssertionCheck(BaseModel):
    id: str
    account_id: str
    account_name: Optional[str] = None
    date: str
    currency: str
    source: Optional[str] = None
    asserted: float
    actual: float
    difference: float
    ok: bool


class BalanceAssertionReport(BaseModel):
    results: list[BalanceAssertionCheck]
    total: int
    failing: int
    earliest_failure: Optional[str] = None
