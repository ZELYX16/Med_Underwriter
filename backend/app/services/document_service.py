from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.config import settings
from app.store.state_store import state_store


class DocumentService:
    """Persist applicant files and metadata only. Never index them in ChromaDB."""

    SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".txt", ".json", ".csv"}
    DOCUMENT_TYPES = {"medical", "claims", "policy", "underwriting", "applicant_profile", "other"}

    def __init__(self) -> None:
        self.storage_root = settings.synthetic_data_directory / "uploads"
        self.storage_root.mkdir(parents=True, exist_ok=True)

    async def upload_document(self, *, upload: UploadFile, applicant_id: str,
                              case_id: str, document_type: str) -> dict[str, Any]:
        applicant_id = applicant_id.strip()
        case_id = case_id.strip()
        document_type = document_type.strip().lower()
        if not applicant_id or not case_id:
            raise ValueError("Applicant ID and case ID are required.")
        if document_type not in self.DOCUMENT_TYPES:
            raise ValueError(f"Unsupported document type: {document_type}")

        filename = Path(upload.filename or "").name.strip()
        filename = re.sub(r"[^\w.\- ]", "_", filename).strip(" .")
        if not filename:
            raise ValueError("Uploaded file must have a filename.")
        extension = Path(filename).suffix.lower()
        if extension not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type '{extension}'. Supported: {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}")

        if state_store.get_applicant(applicant_id) is None:
            raise ValueError(f"Applicant '{applicant_id}' does not exist.")
        case = state_store.get_case(case_id)
        if case is None:
            raise ValueError(f"Case '{case_id}' does not exist.")
        case_applicant_id = str(case.get("applicant_id") or (case.get("applicant_profile") or {}).get("applicant_id") or "").strip()
        if case_applicant_id != applicant_id:
            raise ValueError("Applicant does not match the case.")

        document_id = "DOC-" + uuid.uuid4().hex[:12].upper()
        folder = self.storage_root / applicant_id / case_id
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"{document_id}_{filename}"
        content = await upload.read()
        if not content:
            raise ValueError("File is empty.")
        limit = int(settings.max_upload_mb) * 1024 * 1024
        if len(content) > limit:
            raise ValueError(f"File is too large (limit {settings.max_upload_mb} MB).")
        destination.write_bytes(content)

        metadata = {
            "applicant_id": applicant_id, "case_id": case_id,
            "document_id": document_id, "document_type": document_type,
            "filename": filename, "file_name": filename,
            "file_path": str(destination), "storage_path": str(destination),
            "source": "uploaded", "evidence_scope": "applicant",
            "processing_status": "PENDING", "extraction_status": "PENDING",
            "vector_index_status": "NOT_APPLICABLE",
        }
        applicant_row_created = False
        try:
            state_store.add_applicant_document(
                document_id=document_id, applicant_id=applicant_id,
                document_type=document_type, filename=filename,
                file_path=str(destination), evidence_status="PROVIDED",
                source="uploaded", metadata=metadata,
            )
            applicant_row_created = True
            state_store.add_case_document(
                document_id=document_id, case_id=case_id,
                applicant_id=applicant_id, document_type=document_type,
                filename=filename, file_path=str(destination),
                evidence_status="PROVIDED", source="uploaded", metadata=metadata,
            )
        except Exception:
            if applicant_row_created:
                state_store.delete_applicant_document(document_id)
            state_store.delete_case_document(case_id=case_id, document_id=document_id)
            destination.unlink(missing_ok=True)
            raise

        return {
            "document_id": document_id, "applicant_id": applicant_id,
            "case_id": case_id, "document_type": document_type,
            "filename": filename, "evidence_status": "PROVIDED",
            "processing_status": "PENDING", "extraction_status": "PENDING",
            "indexed": False, "chunks": 0, "storage_path": str(destination),
        }

    def list_applicant_documents(self, applicant_id: str) -> list[dict[str, Any]]:
        return state_store.list_applicant_documents(applicant_id)

    def list_case_documents(self, case_id: str) -> list[dict[str, Any]]:
        return state_store.list_case_documents(case_id)

    def delete_document(self, *, applicant_id: str, case_id: str, document_id: str) -> bool:
        document = state_store.get_applicant_document(document_id)
        if document is None:
            return False
        if document.get("applicant_id") != applicant_id:
            raise ValueError("Document does not belong to applicant.")
        case_docs = state_store.list_case_documents(case_id)
        if not any(item.get("document_id") == document_id for item in case_docs):
            raise ValueError("Document does not belong to case.")
        path = document.get("file_path")
        if path:
            Path(path).unlink(missing_ok=True)
        state_store.delete_case_document(case_id=case_id, document_id=document_id)
        return state_store.delete_applicant_document(document_id)


document_service = DocumentService()
