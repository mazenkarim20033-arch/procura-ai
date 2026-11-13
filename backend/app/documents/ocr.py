"""Optional OCR via Tesseract. Absent by default; callers must check is_available()."""
import shutil
from functools import lru_cache


@lru_cache
def is_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def ocr_page(page, dpi: int = 300) -> tuple[str, float | None]:
    """OCR one PyMuPDF page. Returns (text, mean word confidence 0..1 or None)."""
    import io

    import pytesseract
    from PIL import Image

    pix = page.get_pixmap(dpi=dpi)
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    words = [w for w in data["text"] if w.strip()]
    confs = [float(c) for c, w in zip(data["conf"], data["text"], strict=False) if w.strip() and float(c) >= 0]
    text = pytesseract.image_to_string(image)
    return text, (sum(confs) / len(confs) / 100 if confs and words else None)
