"""Strict Pydantic models for extracted document data.

Extractors first collect raw fields (possibly incomplete), then `validate_extraction` tries to build
the strict model. Failures become `ValidationIssue`s instead of exceptions, so a half-readable
document is still stored, flagged and shown to a human - never silently "fixed".
"""
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LineItem(Strict):
    description: NonEmpty
    quantity: Annotated[Decimal, Field(gt=0)]
    unit_price: Annotated[Decimal, Field(ge=0)]
    line_total: Annotated[Decimal, Field(ge=0)]


class QuotationData(Strict):
    vendor_name: NonEmpty
    quote_no: NonEmpty
    issue_date: date
    valid_until: date | None = None
    currency: Currency
    items: Annotated[list[LineItem], Field(min_length=1)]
    subtotal: Decimal
    tax: Decimal = Decimal(0)
    total: Decimal
    payment_terms: str | None = None
    delivery_days: int | None = None


class InvoiceData(Strict):
    vendor_name: NonEmpty
    invoice_no: NonEmpty
    invoice_date: date
    due_date: date | None = None
    currency: Currency
    items: Annotated[list[LineItem], Field(min_length=1)]
    subtotal: Decimal
    tax: Decimal = Decimal(0)
    total: Decimal
    po_reference: str | None = None


class PurchaseRequestData(Strict):
    request_no: NonEmpty
    requester: NonEmpty
    department: NonEmpty
    request_date: date
    currency: Currency
    supplier: str | None = None
    justification: str | None = None
    items: Annotated[list[LineItem], Field(min_length=1)]
    total: Decimal


class ContractData(Strict):
    contract_no: NonEmpty
    vendor_name: NonEmpty
    effective_date: date
    end_date: date | None = None
    currency: Currency
    total_value: Decimal
    payment_terms: str | None = None


class PolicyHeader(Strict):
    code: NonEmpty
    title: NonEmpty
    version: NonEmpty
    effective_date: date
    category: str | None = None


SCHEMA_BY_TYPE: dict[str, type[Strict]] = {
    "quotation": QuotationData,
    "invoice": InvoiceData,
    "purchase_request": PurchaseRequestData,
    "contract": ContractData,
    "policy": PolicyHeader,
}


class ValidationIssue(BaseModel):
    field: str
    code: str  # missing_field | invalid_value | line_total_mismatch | subtotal_mismatch | ...
    message: str


def schema_issues(model: type[Strict], raw: dict) -> tuple[Strict | None, list[ValidationIssue]]:
    """Build the strict model; return (instance|None, issues). Never raises."""
    try:
        return model.model_validate(raw), []
    except ValidationError as exc:
        issues = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            code = "missing_field" if err["type"] == "missing" else "invalid_value"
            issues.append(ValidationIssue(field=loc, code=code, message=err["msg"]))
        return None, issues
