"""Text extraction: PDF text layer via PyMuPDF, OCR fallback (optional), plain text."""
import re
from dataclasses import dataclass, field

from app.documents import ocr

MIN_TEXT_CHARS = 20  # fewer characters than this on a page => treat as a scan


class UnsupportedDocument(Exception):
    pass


@dataclass
class ParsedPage:
    page_no: int
    text: str
    ocr: bool = False
    ocr_confidence: float | None = None


@dataclass
class ParsedDocument:
    pages: list[ParsedPage]
    warnings: list[str] = field(default_factory=list)

    @property
    def ocr_used(self) -> bool:
        return any(p.ocr for p in self.pages)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)


_ARABIC = re.compile(r"[؀-ۿ]")


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "unknown"
    arabic = sum(1 for c in letters if _ARABIC.match(c))
    return "ar" if arabic / len(letters) > 0.3 else "en"


def parse_bytes(data: bytes, filename: str, mime: str | None = None) -> ParsedDocument:
    name = filename.lower()
    if name.endswith(".pdf") or mime == "application/pdf" or data[:5] == b"%PDF-":
        return _parse_pdf(data)
    if name.endswith(".txt") or (mime or "").startswith("text/"):
        text = data.decode("utf-8", errors="replace")
        pages = [ParsedPage(i + 1, t) for i, t in enumerate(text.split("\f"))]
        return ParsedDocument(pages)
    raise UnsupportedDocument(f"Unsupported file type: {filename} ({mime}). Supported: PDF, TXT.")


def _parse_pdf(data: bytes) -> ParsedDocument:
    import pymupdf

    try:
        pdf = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise UnsupportedDocument(f"Could not open PDF: {exc}") from exc

    pages: list[ParsedPage] = []
    warnings: list[str] = []
    with pdf:
        if pdf.needs_pass:
            raise UnsupportedDocument("PDF is password protected")
        for i, page in enumerate(pdf, start=1):
            text = page.get_text("text")
            if len(text.strip()) >= MIN_TEXT_CHARS:
                pages.append(ParsedPage(i, text))
                continue
            if ocr.is_available():
                text, conf = ocr.ocr_page(page)
                pages.append(ParsedPage(i, text, ocr=True, ocr_confidence=conf))
            else:
                pages.append(ParsedPage(i, text))
                warnings.append(
                    f"page {i} has no text layer and OCR is not available "
                    "(install Tesseract + pytesseract to enable it)"
                )
    return ParsedDocument(pages, warnings)
