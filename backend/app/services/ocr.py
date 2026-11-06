"""Optional, page-aware OCR for scanned PDFs and common image formats.

OCR is deterministic and local. If the native Tesseract binary or an optional
PDF renderer is missing, callers receive an explicit unavailable result and
can route the document for manual review rather than silently losing evidence.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def ocr_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def ocr_image(path: Path) -> dict[str, Any]:
    """Return OCR text and a method marker for an image file."""
    path = Path(path)
    if path.suffix.lower() not in _IMAGE_EXTENSIONS or not ocr_available():
        return {"text": "", "available": False, "method": "ocr_unavailable"}
    try:
        import pytesseract
        from PIL import Image, ImageOps

        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            text = pytesseract.image_to_string(image, config="--psm 6")
        return {"text": text or "", "available": True, "method": "tesseract_image"}
    except Exception as exc:
        return {"text": "", "available": True, "method": "ocr_failed", "error": str(exc)[:240]}


def ocr_pdf_pages(path: Path, max_pages: int = 50, page_numbers: list[int] | None = None) -> list[dict[str, Any]]:
    """OCR pages of a scanned PDF, preferring PyMuPDF and falling back to pdf2image."""
    path = Path(path)
    if not ocr_available():
        return []
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return []

    pages: list[dict[str, Any]] = []
    try:
        import fitz  # PyMuPDF

        document = fitz.open(str(path))
        try:
            selected = page_numbers if page_numbers is not None else list(range(1, min(len(document), max_pages) + 1))
            for page_number in selected:
                if page_number < 1 or page_number > len(document):
                    continue
                page = document[page_number - 1]
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                text = pytesseract.image_to_string(image, config="--psm 6")
                pages.append({"page_number": page_number, "text": text or "", "extraction_method": "tesseract_pdf"})
        finally:
            document.close()
        return pages
    except Exception:
        pages.clear()

    try:
        from pdf2image import convert_from_path

        selected = page_numbers if page_numbers is not None else list(range(1, max_pages + 1))
        for page_number in selected:
            images = convert_from_path(str(path), first_page=page_number, last_page=page_number, dpi=150)
            if not images:
                continue
            image = images[0]
            pages.append({
                "page_number": page_number,
                "text": pytesseract.image_to_string(image, config="--psm 6") or "",
                "extraction_method": "tesseract_pdf2image",
            })
    except Exception:
        return []
    return pages


def ocr_text(path: Path) -> str | None:
    """Backward-compatible helper used by older callers."""
    result = ocr_image(Path(path))
    text = str(result.get("text") or "").strip()
    return text or None
