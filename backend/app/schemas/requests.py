from datetime import date
from decimal import Decimal

from pydantic import Field

from app.schemas.documents import Strict


class ItemIn(Strict):
    description: str | None = None
    quantity: Decimal | None = Field(default=None, ge=0)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal | None = Field(default=None, ge=0)


class RequestCreate(Strict):
    """Everything is optional on purpose: an incomplete request is accepted and the intake report
    lists what is missing, instead of the API rejecting it and hiding the problem."""

    request_no: str | None = Field(default=None, max_length=40)
    requester_name: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=120)
    currency: str | None = Field(default=None, max_length=3)
    supplier_name: str | None = Field(default=None, max_length=255)
    justification: str | None = None
    category: str | None = Field(default=None, max_length=80)
    total_amount: Decimal | None = Field(default=None, ge=0)
    submitted_on: date | None = None
    items: list[ItemIn] = Field(default_factory=list, max_length=200)


class AttachDocument(Strict):
    document_id: str
    role: str | None = Field(default=None, max_length=40)
