"""Deterministic consistency checks on a successfully built extraction model."""
from decimal import Decimal

from app.schemas.documents import (
    Strict,
    ValidationIssue,
    schema_issues,
)

TOLERANCE = Decimal("0.01")


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TOLERANCE


def consistency_issues(model: Strict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    items = getattr(model, "items", None)

    if items:
        for i, it in enumerate(items):
            expected = it.quantity * it.unit_price
            if not _close(expected, it.line_total):
                issues.append(ValidationIssue(
                    field=f"items.{i}.line_total", code="line_total_mismatch",
                    message=f"{it.quantity} x {it.unit_price} = {expected:.2f}, document says {it.line_total}",
                ))
        line_sum = sum((it.line_total for it in items), Decimal(0))
        if hasattr(model, "subtotal"):
            if not _close(line_sum, model.subtotal):
                issues.append(ValidationIssue(
                    field="subtotal", code="subtotal_mismatch",
                    message=f"line totals sum to {line_sum:.2f}, document says {model.subtotal}",
                ))
            if not _close(model.subtotal + model.tax, model.total):
                issues.append(ValidationIssue(
                    field="total", code="total_mismatch",
                    message=f"subtotal + tax = {model.subtotal + model.tax:.2f}, document says {model.total}",
                ))
        elif hasattr(model, "total") and not _close(line_sum, model.total):
            issues.append(ValidationIssue(
                field="total", code="total_mismatch",
                message=f"line totals sum to {line_sum:.2f}, document says {model.total}",
            ))

    issue_date = getattr(model, "issue_date", None)
    valid_until = getattr(model, "valid_until", None)
    if issue_date and valid_until and valid_until < issue_date:
        issues.append(ValidationIssue(
            field="valid_until", code="date_order",
            message="valid_until is before issue_date",
        ))
    due, inv = getattr(model, "due_date", None), getattr(model, "invoice_date", None)
    if due and inv and due < inv:
        issues.append(ValidationIssue(field="due_date", code="date_order", message="due_date is before invoice_date"))
    if hasattr(model, "valid_until") and valid_until is None:
        issues.append(ValidationIssue(
            field="valid_until", code="missing_optional",
            message="quotation has no validity date",
        ))
    return issues


def validate_extraction(model_cls: type[Strict], raw: dict) -> tuple[Strict | None, list[ValidationIssue]]:
    """Schema validation, then (if the schema passed) arithmetic/date consistency."""
    model, issues = schema_issues(model_cls, raw)
    if model is not None:
        issues = consistency_issues(model)
    return model, issues
