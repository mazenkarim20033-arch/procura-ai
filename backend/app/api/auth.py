"""Demo-grade auth: the caller states a role (and optionally an approval authority) via headers; the
server enforces permissions.

This is NOT real authentication (no passwords/SSO). It exists so role separation (only reviewers record
decisions, nobody approves their own request, approval level matches the amount) is enforced server-side
and testable.
"""
from fastapi import Depends, Header

from app.db.enums import Role
from app.errors import PermissionDeniedError
from app.rules.authority import AUTHORITY_ORDER, DEFAULT_AUTHORITY
from app.schemas.identity import CurrentUser


def get_current_user(
    x_demo_role: str = Header(default="requester"),
    x_demo_user: str = Header(default="demo"),
    x_demo_authority: str | None = Header(default=None),
) -> CurrentUser:
    try:
        role = Role(x_demo_role)
    except ValueError:
        raise PermissionDeniedError(f"Unknown role '{x_demo_role}'") from None
    authority = x_demo_authority or DEFAULT_AUTHORITY.get(role)
    if authority is not None and authority not in AUTHORITY_ORDER:
        raise PermissionDeniedError(f"Unknown approval authority '{authority}'")
    return CurrentUser(name=x_demo_user, role=role, authority=authority)


def require_role(*allowed: Role):
    def dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed and user.role != Role.admin:
            raise PermissionDeniedError(f"Role '{user.role}' may not perform this action")
        return user

    return dep
