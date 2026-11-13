"""Document ingestion: parse -> classify -> extract -> validate -> chunk -> persist.

Flushes but never commits: the caller owns the transaction (tests roll back, the API commits).
Embeddings are filled in by the retrieval milestone; chunks are stored with embedding = NULL.
"""
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import enums as E
from app.db.models import Chunk, Document, DocumentPage, Extraction, Policy
from app.documents import chunk as chunking
from app.documents.classify import classify
from app.documents.extract import EXTRACTORS, effective_date
from app.documents.parse import detect_language, parse_bytes
from app.documents.validate import validate_extraction
from app.schemas.documents import SCHEMA_BY_TYPE, ValidationIssue


@dataclass
class IngestResult:
    document: Document
    created: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    chunk_count: int = 0
    policy: Policy | None = None


def ingest_document(
    session: Session, *, filename: str, data: bytes, mime: str | None = None,
    uploaded_by: str | None = None, is_synthetic: bool = False, storage_dir: Path | None = None,
) -> IngestResult:
    sha = hashlib.sha256(data).hexdigest()
    existing = session.execute(select(Document).where(Document.sha256 == sha)).scalar_one_or_none()
    if existing:
        return IngestResult(existing, created=False)

    parsed = parse_bytes(data, filename, mime)  # may raise UnsupportedDocument
    text = parsed.text
    cls = classify(text)

    storage_path = None
    if storage_dir:
        storage_dir.mkdir(parents=True, exist_ok=True)
        path = storage_dir / f"{sha}{Path(filename).suffix.lower()}"
        path.write_bytes(data)
        storage_path = str(path)

    doc = Document(
        filename=filename, sha256=sha, mime=mime or "application/octet-stream",
        doc_type=E.DocType(cls.doc_type), doc_type_confidence=Decimal(str(cls.confidence)),
        language=detect_language(text), is_synthetic=is_synthetic, status=E.DocStatus.parsed,
        ocr_used=parsed.ocr_used, page_count=len(parsed.pages), storage_path=storage_path,
    )
    session.add(doc)
    session.flush()
    for p in parsed.pages:
        session.add(DocumentPage(
            document_id=doc.id, page_no=p.page_no, text=p.text,
            ocr_confidence=Decimal(str(round(p.ocr_confidence, 3))) if p.ocr_confidence is not None else None,
        ))

    result = IngestResult(doc, created=True, warnings=list(parsed.warnings))
    extractor_fn = EXTRACTORS.get(cls.doc_type)
    if extractor_fn:
        ex = extractor_fn(parsed)
        model_cls = SCHEMA_BY_TYPE[cls.doc_type]
        _, result.issues = validate_extraction(model_cls, ex.raw)
        stored_issues = [i.model_dump() for i in result.issues]
        stored_issues += [{"field": "document", "code": "parse_warning", "message": w} for w in parsed.warnings]
        session.add(Extraction(
            document_id=doc.id, schema_name=model_cls.__name__, schema_version="1",
            data_json=ex.raw, field_provenance_json=ex.provenance,
            validation_errors_json=stored_issues, method="rules",
        ))
        doc.status = E.DocStatus.extracted

    if cls.doc_type == "policy":
        result.policy = _create_policy(session, doc, parsed, result)
        drafts = chunking.chunk_policy(parsed, result.policy.code if result.policy else None)
    else:
        drafts = chunking.chunk_text(parsed, label=cls.doc_type.upper())
    for d in drafts:
        session.add(Chunk(
            document_id=doc.id, policy_id=result.policy.id if result.policy else None,
            page_start=d.page_start, page_end=d.page_end, section_path=d.section_path, text=d.text,
            char_start=d.char_start, char_end=d.char_end, token_count=d.token_count,
            metadata_json={"embed_text": d.embed_text, "doc_type": cls.doc_type},
        ))
    result.chunk_count = len(drafts)
    session.flush()
    return result


def _create_policy(session: Session, doc: Document, parsed, result: IngestResult) -> Policy | None:
    ex = EXTRACTORS["policy"](parsed)
    raw = ex.raw
    if not all(raw.get(k) for k in ("code", "title", "version", "effective_date")):
        result.warnings.append("policy header incomplete; policy record not created")
        return None
    eff = effective_date(raw["effective_date"]) if len(str(raw["effective_date"])) == 10 else None
    if eff is None:
        result.warnings.append("policy effective date unreadable; policy record not created")
        return None
    dup = session.execute(
        select(Policy).where(Policy.code == raw["code"], Policy.version == raw["version"])
    ).scalar_one_or_none()
    if dup:
        result.warnings.append(f"policy {raw['code']} v{raw['version']} already exists; not duplicated")
        return None
    policy = Policy(
        code=raw["code"], title=raw["title"], version=raw["version"], effective_from=eff,
        category=raw.get("category"), document_id=doc.id, status="active",
    )
    session.add(policy)
    session.flush()
    return policy
