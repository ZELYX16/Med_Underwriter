from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".json",
    ".csv",
}

EVIDENCE_EXTENSIONS = SUPPORTED_EXTENSIONS | {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


class DocumentLoader:
    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError(
                "chunk_size must be greater than zero."
            )

        if chunk_overlap < 0:
            raise ValueError(
                "chunk_overlap cannot be negative."
            )

        if chunk_overlap >= chunk_size:
            raise ValueError(
                "chunk_overlap must be smaller than chunk_size."
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = self._build_splitter()

    def load_full_text(
        self,
        file_path: str | Path,
    ) -> str:
        """Return the complete source text for reviewer-facing evidence."""
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found: {path}"
            )

        extension = path.suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {extension}"
            )

        if extension == ".pdf":
            text = self._load_pdf(path)
        elif extension == ".txt":
            text = self._load_text(path)
        elif extension == ".json":
            text = self._load_json(path)
        elif extension == ".csv":
            text = self._load_csv(path)
        else:
            text = ""

        return self._clean_source_text(text)

    @staticmethod
    def _clean_source_text(text: str) -> str:
        """Normalize extracted source text without changing its meaning."""
        text = str(text or "")
        text = text.replace("\\r\\n", "\\n").replace("\\r", "\\n")
        text = re.sub(r"[ \\t]+", " ", text)
        text = re.sub(r"\\n{3,}", "\\n\\n", text)
        return text.strip()

    def load_file(
        self,
        file_path: str | Path,
    ) -> list[dict[str, Any]]:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Document not found: {path}"
            )

        extension = path.suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type: {extension}"
            )

        if extension == ".pdf":
            structured = self._structured_chunks(path)
            if structured:
                return structured
            text = self._load_pdf(path)
        elif extension == ".txt":
            text = self._load_text(path)
        elif extension == ".json":
            text = self._load_json(path)
        elif extension == ".csv":
            text = self._load_csv(path)
        else:
            text = ""

        chunks = self._chunk_text(text)

        return [
            {
                "text": chunk,
                "metadata": {
                    "source": str(path),
                    "file_name": path.name,
                    "file_type": extension,
                    "chunk_index": index,
                },
            }
            for index, chunk in enumerate(chunks)
        ]

    def load_full_text(self, file_path: str | Path) -> str:
        """
        Load the complete source document without chunking.
        Used when displaying human-readable evidence.
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        extension = path.suffix.lower()

        if extension == ".pdf":
            text = self._load_pdf(path)
        elif extension == ".txt":
            text = self._load_text(path)
        elif extension == ".json":
            text = self._load_json(path)
        elif extension == ".csv":
            text = self._load_csv(path)
        else:
            raise ValueError(f"Unsupported file type: {extension}")

        return self._clean_source_text(text)

    @staticmethod
    def _clean_source_text(text: str) -> str:
        """Normalize extracted source text while preserving document structure."""
        text = text or ""

        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")
        text = text.replace("\x0c", "\n")

        cleaned_lines = []
        previous_blank = False

        for raw_line in text.split("\n"):
            line = " ".join(raw_line.split())

            if not line:
                if not previous_blank:
                    cleaned_lines.append("")
                previous_blank = True
                continue

            cleaned_lines.append(line)
            previous_blank = False

        return "\n".join(cleaned_lines).strip()

    def load_evidence_file(
        self,
        file_path: str | Path,
        *,
        max_pdf_pages: int = 50,
    ) -> dict[str, Any]:
        """Load page-aware text for evidence extraction and vector indexing.

        Text PDFs retain page numbers. Scanned PDF pages and images use local
        OCR when available. A page is never silently treated as empty evidence.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")
        extension = path.suffix.lower()
        if extension not in EVIDENCE_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {extension}")

        pages: list[dict[str, Any]] = []
        if extension == ".pdf":
            reader = PdfReader(str(path))
            text_pages = []
            for index, page in enumerate(reader.pages[:max_pdf_pages]):
                try:
                    text = (page.extract_text() or "").strip()
                except Exception:
                    text = ""
                text_pages.append({
                    "page_number": index + 1,
                    "text": text,
                    "extraction_method": "pypdf_text" if len(text) >= 30 else "text_layer_empty",
                })
            needs_ocr = any(len(item["text"].strip()) < 30 for item in text_pages)
            if needs_ocr:
                try:
                    from app.services.ocr import ocr_pdf_pages
                    missing_pages = [item["page_number"] for item in text_pages if len(item["text"].strip()) < 30]
                    ocr_pages = ocr_pdf_pages(path, max_pages=max_pdf_pages, page_numbers=missing_pages)
                except Exception:
                    ocr_pages = []
                ocr_by_number = {int(item["page_number"]): item for item in ocr_pages}
                for item in text_pages:
                    if len(item["text"].strip()) < 30:
                        ocr_item = ocr_by_number.get(item["page_number"])
                        if ocr_item and str(ocr_item.get("text") or "").strip():
                            item["text"] = str(ocr_item["text"]).strip()
                            item["extraction_method"] = ocr_item.get("extraction_method", "ocr")
            pages = [item for item in text_pages if str(item["text"]).strip()]
        elif extension in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
            from app.services.ocr import ocr_image
            result = ocr_image(path)
            if str(result.get("text") or "").strip():
                pages = [{"page_number": 1, "text": result["text"].strip(),
                          "extraction_method": result.get("method", "ocr_image")}]
        else:
            if extension == ".txt":
                text = self._load_text(path)
            elif extension == ".json":
                text = self._load_json(path)
            else:
                text = self._load_csv(path)
            if text.strip():
                pages = [{"page_number": None, "text": self._clean_source_text(text),
                          "extraction_method": "native_text"}]

        chunks: list[dict[str, Any]] = []
        for page in pages:
            page_text = self._clean_source_text(str(page.get("text") or ""))
            for index, chunk_text in enumerate(self._chunk_text(page_text)):
                chunks.append({
                    "text": chunk_text,
                    "metadata": {
                        "source": str(path),
                        "file_name": path.name,
                        "file_type": extension,
                        "page_number": page.get("page_number"),
                        "extraction_method": page.get("extraction_method", "text"),
                        "page_chunk_index": index,
                    },
                })
        return {"pages": pages, "chunks": chunks,
                "text": "\n\n".join(str(page["text"]) for page in pages)}

    def load_directory(
        self,
        directory: str | Path,
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        directory = Path(directory)

        if not directory.exists():
            raise FileNotFoundError(
                f"Directory not found: {directory}"
            )

        pattern = "**/*" if recursive else "*"

        documents: list[
            dict[str, Any]
        ] = []

        for path in directory.glob(pattern):
            if not path.is_file():
                continue

            if (
                path.suffix.lower()
                not in SUPPORTED_EXTENSIONS
            ):
                continue

            documents.extend(
                self.load_file(path)
            )

        return documents

    def _structured_chunks(self, path: Path) -> list[dict[str, Any]]:
        """
        Section-aware chunks: tables keep their headers on every row and each
        chunk carries its section. Empty when the layout is not recognised, in
        which case the plain text path is used.
        """
        try:
            from app.rag.structured import parse_pdf, section_chunks

            doc = parse_pdf(path)
            if not doc or not doc["sections"]:
                return []
            return [
                {
                    "text": chunk["text"],
                    "metadata": {
                        "source": str(path),
                        "file_name": path.name,
                        "file_type": ".pdf",
                        "chunk_index": index,
                        "section": chunk["section"],
                        "doc_title": doc["title"],
                        "doc_ref": doc["doc_id"],
                    },
                }
                for index, chunk in enumerate(
                    section_chunks(doc, self.chunk_size)
                )
            ]
        except Exception:
            return []

    def _load_pdf(
        self,
        path: Path,
    ) -> str:
        # Reviewer-facing text: sections with table rows as "Header: value".
        try:
            from app.rag.structured import parse_pdf, render_document

            doc = parse_pdf(path)
            if doc and doc["sections"]:
                return render_document(doc)
        except Exception:
            pass

        reader = PdfReader(str(path))

        pages: list[str] = []

        for page_number, page in enumerate(
            reader.pages,
            start=1,
        ):
            try:
                text = (
                    page.extract_text()
                    or ""
                ).strip()
            except Exception as exc:
                text = (
                    f"[PDF page {page_number} "
                    f"could not be extracted: {exc}]"
                )

            if text:
                pages.append(
                    f"[Page {page_number}]\n{text}"
                )

        return "\n\n".join(pages)

    @staticmethod
    def _load_text(
        path: Path,
    ) -> str:
        return path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

    @staticmethod
    def _load_json(
        path: Path,
    ) -> str:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        return json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        )

    @staticmethod
    def _load_csv(
        path: Path,
    ) -> str:
        rows: list[str] = []

        with path.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as file:
            reader = csv.DictReader(file)

            if reader.fieldnames:
                rows.append(
                    " | ".join(
                        reader.fieldnames
                    )
                )

            for row in reader:
                rows.append(
                    " | ".join(
                        f"{key}: {value or ''}"
                        for key, value in row.items()
                    )
                )

        return "\n".join(rows)

    def _build_splitter(self):
        """
        LangChain's recursive splitter breaks on paragraph, line, sentence
        and word boundaries (in that order) instead of slicing mid-word.
        Falls back to the window slicer below if it is not installed.
        """
        try:
            from langchain_text_splitters import (
                RecursiveCharacterTextSplitter,
            )
        except ImportError:
            try:
                from langchain.text_splitter import (
                    RecursiveCharacterTextSplitter,
                )
            except ImportError:
                return None

        return RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
        )

    def _chunk_text(
        self,
        text: str,
    ) -> list[str]:
        text = text.strip()

        if not text:
            return []

        if len(text) <= self.chunk_size:
            return [text]

        if self._splitter is not None:
            return [
                chunk.strip()
                for chunk in self._splitter.split_text(text)
                if chunk.strip()
            ]

        chunks: list[str] = []

        start = 0
        text_length = len(text)

        while start < text_length:
            end = min(
                start + self.chunk_size,
                text_length,
            )

            chunk = text[start:end].strip()

            if chunk:
                chunks.append(chunk)

            if end >= text_length:
                break

            next_start = (
                end - self.chunk_overlap
            )

            if next_start <= start:
                next_start = end

            start = next_start

        return chunks


document_loader = DocumentLoader()