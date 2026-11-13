"""purchase request intake fields

Revision ID: 0002
Revises: 0001
"""
from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SQL = Path(__file__).resolve().parents[1] / "sql" / "0002_request_fields.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("drop sequence if exists public.request_no_seq")
    op.execute("drop index if exists public.ix_purchase_requests_fingerprint")
    op.execute("alter table public.purchase_requests drop constraint if exists "
               "fk_purchase_requests_source_document_id_documents")
    op.execute("alter table public.purchase_requests drop column if exists source_document_id, "
               "drop column if exists supplier_name, drop column if exists requester_name")
