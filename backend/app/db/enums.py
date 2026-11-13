from enum import StrEnum


class Role(StrEnum):
    requester = "requester"
    reviewer = "reviewer"
    admin = "admin"


class DocType(StrEnum):
    policy = "policy"
    quotation = "quotation"
    invoice = "invoice"
    contract = "contract"
    purchase_request = "purchase_request"
    other = "other"


class DocStatus(StrEnum):
    uploaded = "uploaded"
    parsed = "parsed"
    extracted = "extracted"
    indexed = "indexed"
    failed = "failed"


class RequestStatus(StrEnum):
    submitted = "submitted"
    assessed = "assessed"
    info_requested = "info_requested"
    approved = "approved"
    rejected = "rejected"


class FindingCategory(StrEnum):
    confirmed_violation = "confirmed_violation"
    potential_violation = "potential_violation"
    missing_information = "missing_information"
    compliant = "compliant"
    inconclusive = "inconclusive"


class FindingSource(StrEnum):
    rule = "rule"
    llm = "llm"


class EvidenceKind(StrEnum):
    policy_chunk = "policy_chunk"
    request_field = "request_field"
    document_span = "document_span"
    quotation = "quotation"


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ComplianceStatus(StrEnum):
    """The AI never says 'approved'; only a human decision can approve."""

    no_issues_found = "no_issues_found"
    issues_found = "issues_found"
    needs_information = "needs_information"
    inconclusive = "inconclusive"


class DecisionAction(StrEnum):
    approve = "approve"
    reject = "reject"
    request_info = "request_info"


class Verdict(StrEnum):
    agree = "agree"
    disagree = "disagree"
    unsure = "unsure"
