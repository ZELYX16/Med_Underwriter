from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings
from app.rag.document_loader import document_loader
from app.security.guardrails import guardrails
from app.store.vector_store import vector_store


class DocumentIndexer:
    COLLECTION_NAME = "applicant_documents"

    DOCUMENT_TYPE_MAP = {
        "medical": "medical",
        "claims": "claims",
        "policy": "policy",
        "underwriting": "underwriting",
        "applicants": "applicant_profile",
    }

    SUPPORTED_EXTENSIONS = {
        ".pdf",
        ".txt",
        ".json",
        ".csv",
    }

    def index_applicant(
        self,
        applicant_id: str,
        applicant_directory: str | Path,
    ) -> dict[str, Any]:
        directory = Path(
            applicant_directory
        )

        if not directory.exists():
            raise FileNotFoundError(
                f"Applicant directory not found: {directory}"
            )

        files = sorted(
            path
            for path in directory.rglob("*")
            if (
                path.is_file()
                and path.suffix.lower()
                in self.SUPPORTED_EXTENSIONS
            )
        )

        if not files:
            return {
                "applicant_id": applicant_id,
                "indexed": False,
                "documents": 0,
                "chunks": 0,
                "details": [],
                "message": (
                    "No supported documents found."
                ),
            }

        total_chunks = 0
        indexed_documents: list[
            dict[str, Any]
        ] = []

        for file_path in files:
            document_type = (
                self._get_document_type(
                    file_path
                )
            )

            document_id = (
                self._extract_document_id(
                    file_path
                )
            )

            try:
                chunks = (
                    document_loader.load_file(
                        file_path
                    )
                )
            except Exception as exc:
                indexed_documents.append(
                    {
                        "document_id": document_id,
                        "document_type": document_type,
                        "file_name": file_path.name,
                        "chunks": 0,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                continue

            if not chunks:
                continue

            documents: list[str] = []
            metadatas: list[
                dict[str, Any]
            ] = []
            ids: list[str] = []

            for index, chunk in enumerate(
                chunks
            ):
                text = str(
                    chunk.get(
                        "text",
                        "",
                    )
                ).strip()

                if not text:
                    continue

                chunk_id = (
                    f"{applicant_id}:"
                    f"{document_id}:"
                    f"{index}"
                )

                metadata = {
                    "applicant_id": applicant_id,
                    "document_id": document_id,
                    "document_type": document_type,
                    "evidence_scope": "applicant",
                    "source": (
                        "synthetic_applicant_document"
                    ),
                    # Keep both names for compatibility with existing
                    # retriever/document-service metadata.
                    "filename": file_path.name,
                    "file_name": file_path.name,
                    "file_path": str(file_path),
                    "storage_path": str(file_path),
                    "chunk_index": index,
                }
                flags = guardrails.scan_document_text(text)
                if flags:
                    metadata["security_flag"] = ",".join(flags)

                documents.append(text)
                metadatas.append(metadata)
                ids.append(chunk_id)

            if not documents:
                continue

            try:
                vector_store.add_documents(
                    collection_name=(
                        self.COLLECTION_NAME
                    ),
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids,
                )

                total_chunks += len(
                    documents
                )

                indexed_documents.append(
                    {
                        "document_id": document_id,
                        "document_type": document_type,
                        "file_name": file_path.name,
                        "chunks": len(documents),
                        "status": "indexed",
                    }
                )

            except Exception as exc:
                indexed_documents.append(
                    {
                        "document_id": document_id,
                        "document_type": document_type,
                        "file_name": file_path.name,
                        "chunks": 0,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        successful_documents = sum(
            1
            for item in indexed_documents
            if item.get("status") == "indexed"
        )

        failed_documents = sum(
            1
            for item in indexed_documents
            if item.get("status") == "failed"
        )

        return {
            "applicant_id": applicant_id,
            "indexed": successful_documents > 0,
            "documents": successful_documents,
            "failed_documents": failed_documents,
            "chunks": total_chunks,
            "details": indexed_documents,
        }

    def index_all_applicants(
        self,
        applicants_root: str | Path | None = None,
    ) -> dict[str, Any]:
        root = Path(
            applicants_root
            or (
                settings.data_directory
                / "synthetic"
                / "applicants"
            )
        )

        if not root.exists():
            raise FileNotFoundError(
                f"Applicants directory not found: {root}"
            )

        applicant_directories = sorted(
            path
            for path in root.iterdir()
            if path.is_dir()
        )

        results: list[
            dict[str, Any]
        ] = []

        for directory in applicant_directories:
            result = self.index_applicant(
                applicant_id=directory.name,
                applicant_directory=directory,
            )
            results.append(result)

        return {
            "root": str(root),
            "applicants_processed": len(
                results
            ),
            "documents_indexed": sum(
                result.get(
                    "documents",
                    0,
                )
                for result in results
            ),
            "documents_failed": sum(
                result.get(
                    "failed_documents",
                    0,
                )
                for result in results
            ),
            "chunks_indexed": sum(
                result.get(
                    "chunks",
                    0,
                )
                for result in results
            ),
            "results": results,
        }

    def index_directory(
        self,
        directory: str | Path,
        applicant_id: str | None = None,
    ) -> dict[str, Any]:
        path = Path(directory)

        resolved_applicant_id = (
            applicant_id
            or path.name
        )

        return self.index_applicant(
            applicant_id=resolved_applicant_id,
            applicant_directory=path,
        )

    def _get_document_type(
        self,
        file_path: Path,
    ) -> str:
        parts = {
            part.lower()
            for part in file_path.parts
        }

        for (
            folder,
            document_type,
        ) in self.DOCUMENT_TYPE_MAP.items():
            if folder in parts:
                return document_type

        return "other"

    @staticmethod
    def _extract_document_id(
        file_path: Path,
    ) -> str:
        filename = file_path.stem

        if "_" in filename:
            return filename.split(
                "_",
                1,
            )[0]

        return filename


document_indexer = DocumentIndexer()