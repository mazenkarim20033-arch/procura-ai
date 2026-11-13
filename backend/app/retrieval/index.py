"""Embed stored chunks. Chunks are embedded from their context-prefixed text (metadata_json.embed_text),
while `Chunk.text` stays verbatim for citation."""
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import enums as E
from app.db.models import Chunk, Document
from app.retrieval.base import Embedder

BATCH = 32


def index_chunks(session: Session, embedder: Embedder, *, reindex: bool = False) -> int:
    """Embed chunks that have no embedding (or a different model, or all when reindex=True).
    Flushes only; the caller commits. Returns the number of chunks embedded."""
    q = select(Chunk)
    if not reindex:
        q = q.where(
            (Chunk.embedding.is_(None)) | (Chunk.embedding_model.is_distinct_from(embedder.name))
        )
    chunks = session.execute(q.order_by(Chunk.document_id, Chunk.char_start)).scalars().all()
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        vectors = embedder.embed_documents([c.metadata_json.get("embed_text") or c.text for c in batch])
        for chunk, vec in zip(batch, vectors, strict=True):
            chunk.embedding = vec
            chunk.embedding_model = embedder.name
    session.flush()

    # A document is "indexed" once none of its chunks lack an embedding.
    pending = select(Chunk.document_id).where(Chunk.embedding.is_(None))
    session.execute(
        update(Document)
        .where(Document.status == E.DocStatus.extracted, Document.id.not_in(pending),
               Document.id.in_(select(Chunk.document_id)))
        .values(status=E.DocStatus.indexed)
    )
    session.flush()
    return len(chunks)


def embedding_stats(session: Session) -> dict:
    total = session.execute(select(func.count()).select_from(Chunk)).scalar_one()
    embedded = session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.embedding.is_not(None))
    ).scalar_one()
    models = session.execute(select(Chunk.embedding_model).distinct()).scalars().all()
    return {"chunks": total, "embedded": embedded, "models": [m for m in models if m]}
