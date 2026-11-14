"""Approval authority levels (lowest to highest). The strings match PRC-001 clauses 2.1-2.4, see
policy_rules.APPROVERS. Lives in the rules layer so both the API and the decision rules can use it."""
from app.db.enums import Role

AUTHORITY_ORDER = ["department manager", "procurement officer", "finance director", "chief financial officer"]
DEFAULT_AUTHORITY = {Role.reviewer: "procurement officer", Role.admin: "chief financial officer"}


def authority_rank(authority: str | None) -> int:
    return AUTHORITY_ORDER.index(authority) if authority in AUTHORITY_ORDER else -1
