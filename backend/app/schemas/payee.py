import uuid
from datetime import date as _Date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.fiscal.registry import TaxIdKind
from app.schemas.category import CategoryRead


class TaxIdInput(BaseModel):
    """One fiscal document on the way in.

    `kind` is the closed enum, so an unknown document type is a 422 rather
    than an uninterpretable row. The value arrives however the user typed it
    and is normalised per kind before storage; an empty value means "remove
    this document".
    """

    kind: TaxIdKind
    value: str = Field(..., max_length=120)


class TaxIdRead(BaseModel):
    kind: str
    value: str

    model_config = ConfigDict(from_attributes=True)


class PayeeCreate(BaseModel):
    name: str = Field(..., max_length=255)
    type: str = "merchant"
    notes: Optional[str] = Field(None, max_length=1000)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=500)
    default_payment_terms_days: Optional[int] = Field(None, ge=0, le=365)
    tax_ids: list[TaxIdInput] = []


class PayeeUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    type: Optional[str] = None
    is_favorite: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=1000)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=500)
    default_payment_terms_days: Optional[int] = Field(None, ge=0, le=365)
    # Absent leaves the documents alone. Present replaces the whole set, so
    # the caller sends what should remain rather than a diff.
    tax_ids: Optional[list[TaxIdInput]] = None


class PayeeRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    type: str
    is_favorite: bool
    notes: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    default_payment_terms_days: Optional[int] = None
    tax_ids: list[TaxIdRead] = []
    created_at: datetime
    transaction_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class PayeeSummary(BaseModel):
    payee: PayeeRead
    total_spent: Decimal = Decimal("0")
    total_received: Decimal = Decimal("0")
    transaction_count: int = 0
    most_common_category: Optional[CategoryRead] = None
    last_transaction_date: Optional[_Date] = None


class PayeeMergeRequest(BaseModel):
    source_ids: list[uuid.UUID]
    target_id: uuid.UUID


class PayeeBulkDeleteRequest(BaseModel):
    ids: list[uuid.UUID]
