from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.config import settings
from app.rag.document_loader import document_loader
from app.security.guardrails import guardrails
from app.store.state_store import state_store
from app.store.vector_store import vector_store


logger = logging.getLogger(__name__)


class DocumentService:
    COLLECTION_NAME = "applicant_documents"

    SUPPORTED_EXTENSIONS = {
        ".pdf",
        ".txt",
        ".json",
        ".csv",
    }

    DOCUMENT_TYPES = {
        "medical",
        "claims",
        "policy",
        "underwriting",
        "applicant_profile",
        "other",
    }

    def __init__(self) -> None:
        self.storage_root = (
            settings.synthetic_data_directory
            / "uploads"
        )

        self.storage_root.mkdir(
            parents=True,
            exist_ok=True,
        )

    # =========================================================
    # UPLOAD
    # =========================================================

    async def upload_document(
        self,
        *,
        upload: UploadFile,
        applicant_id: str,
        case_id: str,
        document_type: str,
    ) -> dict[str, Any]:

        applicant_id = applicant_id.strip()
        case_id = case_id.strip()
        document_type = document_type.strip().lower()

        if not applicant_id:
            raise ValueError(
                "Applicant ID is required."
            )

        if not case_id:
            raise ValueError(
                "Case ID is required."
            )

        if document_type not in self.DOCUMENT_TYPES:
            raise ValueError(
                f"Unsupported document type: {document_type}"
            )

        filename = Path(
            upload.filename or ""
        ).name.strip()
        # Keep only safe characters so the name can't escape the folder or
        # smuggle odd characters into paths and logs.
        filename = re.sub(r"[^\w.\- ]", "_", filename).strip(" .")

        if not filename:
            raise ValueError(
                "Uploaded file must have a filename."
            )

        extension = Path(
            filename
        ).suffix.lower()

        if extension not in self.SUPPORTED_EXTENSIONS:
            supported = ", ".join(
                sorted(self.SUPPORTED_EXTENSIONS)
            )

            raise ValueError(
                f"Unsupported file type '{extension}'. "
                f"Supported types: {supported}"
            )

        # -----------------------------------------------------
        # Validate applicant
        # -----------------------------------------------------

        applicant = state_store.get_applicant(
            applicant_id
        )

        if applicant is None:
            raise ValueError(
                f"Applicant '{applicant_id}' does not exist."
            )

        # -----------------------------------------------------
        # Validate case
        # -----------------------------------------------------

        case = state_store.get_case(
            case_id
        )

        if case is None:
            raise ValueError(
                f"Case '{case_id}' does not exist."
            )

        case_applicant_id = str(
            case.get("applicant_id")
            or (
                case.get("applicant_profile")
                or {}
            ).get("applicant_id")
            or ""
        ).strip()

        if case_applicant_id != applicant_id:
            raise ValueError(
                "Applicant does not match the case."
            )

        # -----------------------------------------------------
        # Storage
        # -----------------------------------------------------

        document_id = self._document_id()

        applicant_directory = (
            self.storage_root
            / applicant_id
            / case_id
        )

        applicant_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination = (
            applicant_directory
            / f"{document_id}_{filename}"
        )

        await self._save_upload(
            upload=upload,
            destination=destination,
        )

        try:
            # -------------------------------------------------
            # Extract
            # -------------------------------------------------

            extraction = self._extract_document(
                destination
            )

            text = extraction["text"]

            if not text.strip():
                raise ValueError(
                    "No readable text was extracted "
                    "from the uploaded document."
                )

            chunks = extraction["chunks"]

            # -------------------------------------------------
            # Chroma
            # -------------------------------------------------

            indexed_chunks = self._index_chunks(
                applicant_id=applicant_id,
                case_id=case_id,
                document_id=document_id,
                filename=filename,
                document_type=document_type,
                chunks=chunks,
            )

            # -------------------------------------------------
            # Metadata
            # -------------------------------------------------

            metadata = {
                "applicant_id": applicant_id,
                "case_id": case_id,
                "document_id": document_id,
                "document_type": document_type,
                "filename": filename,
                "evidence_scope": "applicant",
                "source": "uploaded",
                "storage_path": str(destination),
                "chunk_count": len(chunks),
            }

            # -------------------------------------------------
            # Applicant document
            # -------------------------------------------------

            state_store.add_applicant_document(
                document_id=document_id,
                applicant_id=applicant_id,
                document_type=document_type,
                filename=filename,
                file_path=str(destination),
                evidence_status="PROVIDED",
                source="uploaded",
                metadata=metadata,
            )

            # -------------------------------------------------
            # Case document
            # -------------------------------------------------

            state_store.add_case_document(
                document_id=document_id,
                case_id=case_id,
                applicant_id=applicant_id,
                document_type=document_type,
                filename=filename,
                file_path=str(destination),
                evidence_status="PROVIDED",
                source="uploaded",
                metadata=metadata,
            )

            return {
                "document_id": document_id,
                "applicant_id": applicant_id,
                "case_id": case_id,
                "document_type": document_type,
                "filename": filename,
                "evidence_status": "PROVIDED",
                "indexed": indexed_chunks > 0,
                "chunks": indexed_chunks,
                "storage_path": str(destination),
            }

        except Exception:
            if destination.exists():
                destination.unlink()

            raise

    # =========================================================
    # EXTRACTION
    # =========================================================

    def _extract_document(
        self,
        file_path: Path,
    ) -> dict[str, Any]:

        chunks = document_loader.load_file(
            file_path
        )

        normalized_chunks: list[
            dict[str, Any]
        ] = []

        for index, chunk in enumerate(chunks):

            text = str(
                chunk.get("text", "")
            ).strip()

            if not text:
                continue

            metadata = dict(
                chunk.get("metadata")
                or {}
            )

            metadata["chunk_index"] = index

            normalized_chunks.append(
                {
                    "text": text,
                    "metadata": metadata,
                }
            )

        text = "\n\n".join(
            chunk["text"]
            for chunk in normalized_chunks
        )

        return {
            "text": text,
            "chunks": normalized_chunks,
        }

    # =========================================================
    # CHROMA INDEXING
    # =========================================================

    def _index_chunks(
        self,
        *,
        applicant_id: str,
        case_id: str,
        document_id: str,
        filename: str,
        document_type: str,
        chunks: list[dict[str, Any]],
    ) -> int:

        if not chunks:
            return 0

        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        ids: list[str] = []

        for index, chunk in enumerate(chunks):

            text = str(
                chunk.get("text", "")
            ).strip()

            if not text:
                continue

            chunk_metadata = dict(
                chunk.get("metadata")
                or {}
            )

            metadata = {
                **chunk_metadata,
                "applicant_id": applicant_id,
                "case_id": case_id,
                "document_id": document_id,
                "document_type": document_type,
                "evidence_scope": "applicant",
                "source": "uploaded",
                "filename": filename,
                "chunk_index": index,
            }
            flags = guardrails.scan_document_text(text)
            if flags:
                metadata["security_flag"] = ",".join(flags)
                logger.warning(
                    "Document %s chunk %s flagged: %s",
                    filename,
                    index,
                    metadata["security_flag"],
                )

            chunk_id = (
                f"{applicant_id}:"
                f"{document_id}:"
                f"{index}"
            )

            documents.append(text)
            metadatas.append(metadata)
            ids.append(chunk_id)

        if not documents:
            return 0

        return vector_store.add_documents(
            collection_name=self.COLLECTION_NAME,
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )

    # =========================================================
    # LIST
    # =========================================================

    def list_applicant_documents(
        self,
        applicant_id: str,
    ) -> list[dict[str, Any]]:

        return state_store.list_applicant_documents(
            applicant_id
        )

    def list_case_documents(
        self,
        case_id: str,
    ) -> list[dict[str, Any]]:

        return state_store.list_case_documents(
            case_id
        )

    # =========================================================
    # DELETE
    # =========================================================

    def delete_document(
        self,
        *,
        applicant_id: str,
        case_id: str,
        document_id: str,
    ) -> bool:

        document = (
            state_store.get_applicant_document(
                document_id
            )
        )

        if document is None:
            return False

        if document["applicant_id"] != applicant_id:
            raise ValueError(
                "Document does not belong to applicant."
            )

        case_documents = (
            state_store.list_case_documents(
                case_id
            )
        )

        belongs_to_case = any(
            item["document_id"] == document_id
            for item in case_documents
        )

        if not belongs_to_case:
            raise ValueError(
                "Document does not belong to case."
            )

        # -----------------------------------------------------
        # Delete physical file
        # -----------------------------------------------------

        file_path = document.get(
            "file_path"
        )

        if file_path:
            storage_path = Path(file_path)

            if storage_path.exists():
                storage_path.unlink()

        # -----------------------------------------------------
        # Delete DB records
        # -----------------------------------------------------

        state_store.delete_case_document(
            case_id=case_id,
            document_id=document_id,
        )

        return state_store.delete_applicant_document(
            document_id
        )

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _document_id() -> str:
        return (
            "DOC-"
            + uuid.uuid4()
            .hex[:12]
            .upper()
        )

    @staticmethod
    async def _save_upload(
        *,
        upload: UploadFile,
        destination: Path,
    ) -> None:

        content = await upload.read()

        if not content:
            raise ValueError(
                "Uploaded file is empty."
            )

        limit = int(settings.max_upload_mb) * 1024 * 1024
        if len(content) > limit:
            raise ValueError(
                f"File is too large (limit {settings.max_upload_mb} MB)."
            )

        destination.write_bytes(
            content
        )


document_service = DocumentService()