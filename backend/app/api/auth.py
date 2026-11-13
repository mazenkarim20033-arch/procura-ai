"""Demo-grade auth: the caller states a role via headers; the server enforces permissions.

This is NOT real authentication (no passwords/SSO). It exists so role separation
(e.g. only reviewers record decisions) is enforced server-side and testable.
"""
from dataclasses import dataclass

from fastapi import Depends, Header

from app.db.enums import Role
from app.errors import PermissionDeniedError


@dataclass(frozen=True)
class CurrentUser:
    name: str
    role: Role


def get_current_user(
    x_demo_role: str = Header(default="requester"),
    x_demo_user: str = Header(default="demo"),
) -> CurrentUser:
    try:
        role = Role(x_demo_role)
    except ValueError:
        raise PermissionDeniedError(f"Unknown role '{x_demo_role}'") from None
    return CurrentUser(name=x_demo_user, role=role)


def require_role(*allowed: Role):
    def dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed and user.role != Role.admin:
            raise PermissionDeniedError(f"Role '{user.role}' may not perform this action")
        return user

    return dep
