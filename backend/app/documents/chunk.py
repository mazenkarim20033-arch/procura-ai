"""Structure-aware chunking. Policies are split at numbered clauses (one chunk per clause) so a
citation points at exactly one rule; unstructured text falls back to paragraph packing.

`text` is stored verbatim (it is what gets quoted back as evidence). `embed_text` adds a context
header and is only used for embedding later (milestone 5)."""
import re
from dataclasses import dataclass

from app.documents.parse import ParsedDocument

MAX_WORDS = 300
_SECTION = re.compile(r"^\s*(?:Section\s+)?(?P<num>\d+)\.\s+(?P<title>[A-Z][^\n]{2,80})$")
_CLAUSE = re.compile(r"^\s*(?P<num>\d+\.\d+(?:\.\d+)?)\s+(?P<body>\S.*)$")


@dataclass
class ChunkDraft:
    text: str
    section_path: str | None
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    token_count: int
    embed_text: str


def _words(text: str) -> int:
    return len(text.split())


def _split_long(text: str) -> list[str]:
    if _words(text) <= MAX_WORDS:
        return [text]
    parts, current, count = [], [], 0
    for sentence in re.split(r"(?<=[.;])\s+", text):
        n = _words(sentence)
        if current and count + n > MAX_WORDS:
            parts.append(" ".join(current))
            current, count = [], 0
        current.append(sentence)
        count += n
    if current:
        parts.append(" ".join(current))
    return parts


def chunk_policy(doc: ParsedDocument, policy_code: str | None = None) -> list[ChunkDraft]:
    """One chunk per numbered clause; continuation lines belong to the clause above them."""
    prefix = policy_code or "POLICY"
    chunks: list[ChunkDraft] = []
    section: str | None = None
    cur: dict | None = None

    def flush() -> None:
        nonlocal cur
        if not cur:
            return
        body = " ".join(cur["lines"]).strip()
        for i, piece in enumerate(_split_long(body)):
            path = f"{prefix} > {section}" if section else prefix
            path = f"{path} > {cur['num']}" + (f" (part {i + 1})" if i else "")
            chunks.append(ChunkDraft(
                text=piece, section_path=path, page_start=cur["page"], page_end=cur["page_end"],
                char_start=cur["start"], char_end=cur["end"], token_count=_words(piece),
                embed_text=f"[{path}] {piece}",
            ))
        cur = None

    for page in doc.pages:
        pos = 0
        for raw in page.text.split("\n"):
            start, end = pos, pos + len(raw)
            pos = end + 1
            clause = _CLAUSE.match(raw)
            sec = _SECTION.match(raw)
            if clause:
                flush()
                cur = {"num": clause.group("num"), "lines": [clause.group("body").strip()],
                       "page": page.page_no, "page_end": page.page_no, "start": start, "end": end}
            elif sec:
                flush()
                section = f"{sec.group('num')} {sec.group('title').strip()}"
            elif cur is not None and raw.strip() and not raw.lstrip().lower().startswith(("synthetic", "page ")):
                cur["lines"].append(raw.strip())
                cur["end"], cur["page_end"] = end, page.page_no
            elif not raw.strip():
                continue
    flush()
    return chunks


def chunk_text(doc: ParsedDocument, label: str = "DOC") -> list[ChunkDraft]:
    """Fallback: pack paragraphs up to MAX_WORDS."""
    chunks: list[ChunkDraft] = []
    for page in doc.pages:
        pos = 0
        for para in re.split(r"\n\s*\n", page.text):
            idx = page.text.find(para, pos)
            pos = idx + len(para) if idx >= 0 else pos
            body = " ".join(para.split())
            if not body:
                continue
            for piece in _split_long(body):
                chunks.append(ChunkDraft(
                    text=piece, section_path=f"{label} p.{page.page_no}", page_start=page.page_no,
                    page_end=page.page_no, char_start=max(idx, 0), char_end=max(idx, 0) + len(para),
                    token_count=_words(piece), embed_text=f"[{label} p.{page.page_no}] {piece}",
                ))
    return chunks
