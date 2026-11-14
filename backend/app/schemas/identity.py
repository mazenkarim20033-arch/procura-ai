from dataclasses import dataclass

from app.db.enums import Role


@dataclass(frozen=True)
class CurrentUser:
    """The (demo-grade) caller identity; see app/api/auth.py for how it is established."""

    name: str
    role: Role
    authority: str | None = None
