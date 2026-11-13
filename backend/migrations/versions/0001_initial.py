"""initial schema

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0001_initial.sql"


def upgrade() -> None:
    # Single source of truth: the generated DDL file (models + triggers). It contains no '%'
    # characters, so the driver's parameter parsing cannot misread it.
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("drop schema public cascade; create schema public;")
