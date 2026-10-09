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


class DocumentLoader:
    def __init__(
        self,
        chunk_size: int = 1200,
        chunk_overlap: int = 200,
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

    def _load_pdf(
        self,
        path: Path,
    ) -> str:
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

    def _chunk_text(
        self,
        text: str,
    ) -> list[str]:
        text = text.strip()

        if not text:
            return []

        if len(text) <= self.chunk_size:
            return [text]

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