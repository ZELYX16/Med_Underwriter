from __future__ import annotations
from pathlib import Path
from typing import Any

class DocumentIndexer:
    """Compatibility shim: applicant-to-Chroma indexing is intentionally disabled."""
    @staticmethod
    def _disabled() -> None:
        raise RuntimeError("Applicant document indexing is disabled. Register applicant files in SQLite with app.services.seed_database; shared knowledge uses app.services.index_data.")
    def index_applicant(self, applicant_id: str, applicant_directory: str | Path) -> dict[str, Any]:
        self._disabled()
    def index_all_applicants(self, applicants_root: str | Path | None = None) -> dict[str, Any]:
        self._disabled()
    def index_directory(self, directory: str | Path, applicant_id: str | None = None) -> dict[str, Any]:
        self._disabled()

document_indexer = DocumentIndexer()
