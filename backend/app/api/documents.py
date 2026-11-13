from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import CurrentUser, get_current_user
from app.db import enums as E
from app.db.models import Chunk, Document, DocumentPage, Extraction
from app.db.session import get_session
from app.documents.parse import UnsupportedDocument
from app.errors import DomainError, NotFoundError, PermissionDeniedError
from app.services import audit
from app.services.ingest import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_BYTES = 15 * 1024 * 1024
STORAGE_DIR = Path("storage")


class UnsupportedMedia(DomainError):
    status_code = 422
    code = "unsupported_document"


class TooLarge(DomainError):
    status_code = 413
    code = "file_too_large"


def _doc_summary(d: Document) -> dict:
    return {
        "id": str(d.id), "filename": d.filename, "doc_type": d.doc_type.value,
        "doc_type_confidence": float(d.doc_type_confidence) if d.doc_type_confidence is not None else None,
        "language": d.language, "status": d.status.value, "page_count": d.page_count,
        "ocr_used": d.ocr_used, "is_synthetic": d.is_synthetic, "created_at": d.created_at.isoformat(),
    }


@router.post("", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise TooLarge(f"File exceeds {MAX_BYTES // (1024 * 1024)} MB")
    try:
        result = ingest_document(
            session, filename=file.filename or "upload", data=data, mime=file.content_type,
            uploaded_by=user.name, storage_dir=STORAGE_DIR,
        )
    except UnsupportedDocument as exc:
        raise UnsupportedMedia(str(exc)) from exc

    if result.created and result.document.doc_type == E.DocType.policy and user.role != E.Role.admin:
        session.rollback()
        if result.document.storage_path:
            Path(result.document.storage_path).unlink(missing_ok=True)
        raise PermissionDeniedError("Only admins can upload policy documents")

    if result.created:
        audit.append(
            session, actor_type="user", actor_id=user.name, action="document.uploaded",
            entity_type="document", entity_id=str(result.document.id),
            payload={"filename": result.document.filename, "doc_type": result.document.doc_type.value,
                     "sha256": result.document.sha256},
        )
    session.commit()
    return {
        **_doc_summary(result.document), "duplicate": not result.created,
        "chunk_count": result.chunk_count,
        "validation_issues": [i.model_dump() for i in result.issues], "warnings": result.warnings,
    }


@router.get("")
def list_documents(
    doc_type: str | None = None, limit: int = 100, session: Session = Depends(get_session),
) -> list[dict]:
    q = select(Document).order_by(Document.created_at.desc()).limit(min(limit, 500))
    if doc_type:
        q = q.where(Document.doc_type == E.DocType(doc_type))
    return [_doc_summary(d) for d in session.execute(q).scalars()]


@router.get("/{document_id}")
def get_document(document_id: UUID, session: Session = Depends(get_session)) -> dict:
    doc = session.get(Document, document_id)
    if not doc:
        raise NotFoundError("Document not found")
    extraction = session.execute(
        select(Extraction).where(Extraction.document_id == doc.id).order_by(Extraction.created_at.desc())
    ).scalars().first()
    pages = session.execute(
        select(DocumentPage).where(DocumentPage.document_id == doc.id).order_by(DocumentPage.page_no)
    ).scalars().all()
    chunk_count = session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id)
    ).scalar_one()
    return {
        **_doc_summary(doc),
        "pages": [{"page_no": p.page_no, "text": p.text} for p in pages],
        "chunk_count": chunk_count,
        "extraction": None if not extraction else {
            "schema": extraction.schema_name, "method": extraction.method,
            "data": extraction.data_json, "provenance": extraction.field_provenance_json,
            "validation_issues": extraction.validation_errors_json,
        },
    }
