from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings
from app.rag.document_loader import document_loader
from app.store.vector_store import vector_store


class DocumentIndexer:
    """
    Indexes MedUnderwrite documents into Chroma.

    Applicant documents are stored in the applicant_documents
    collection with metadata required for filtered retrieval.
    """

    COLLECTION_NAME = "applicant_documents"

    DOCUMENT_TYPE_MAP = {
        "medical": "medical",
        "claims": "claims",
        "policy": "policy",
        "underwriting": "underwriting",
        "applicants": "applicant_profile",
    }

    def index_applicant(
        self,
        applicant_id: str,
        applicant_directory: str | Path,
    ) -> dict[str, Any]:
        directory = Path(applicant_directory)

        if not directory.exists():
            raise FileNotFoundError(
                f"Applicant directory not found: {directory}"
            )

        files = [
            path
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix.lower()
            in {".pdf", ".txt", ".json", ".csv"}
        ]

        if not files:
            return {
                "applicant_id": applicant_id,
                "indexed": False,
                "documents": 0,
                "chunks": 0,
                "message": "No supported documents found.",
            }

        total_chunks = 0
        indexed_documents = []

        for file_path in files:
            document_type = self._get_document_type(
                file_path
            )

            document_id = self._extract_document_id(
                file_path
            )

            chunks = document_loader.load_file(
                file_path
            )

            if not chunks:
                continue

            documents = []
            metadatas = []
            ids = []

            for index, chunk in enumerate(chunks):
                text = chunk.get("text", "").strip()

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
                    "source": "synthetic_applicant_document",
                    "file_name": file_path.name,
                    "file_path": str(file_path),
                    "chunk_index": index,
                }

                documents.append(text)
                metadatas.append(metadata)
                ids.append(chunk_id)

            if documents:
                vector_store.add_documents(
                    collection_name=self.COLLECTION_NAME,
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids,
                )

                total_chunks += len(documents)

                indexed_documents.append(
                    {
                        "document_id": document_id,
                        "document_type": document_type,
                        "file_name": file_path.name,
                        "chunks": len(documents),
                    }
                )

        return {
            "applicant_id": applicant_id,
            "indexed": bool(indexed_documents),
            "documents": len(indexed_documents),
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

        applicant_directories = [
            path
            for path in root.iterdir()
            if path.is_dir()
        ]

        results = []

        for directory in sorted(
            applicant_directories
        ):
            applicant_id = directory.name

            result = self.index_applicant(
                applicant_id=applicant_id,
                applicant_directory=directory,
            )

            results.append(result)

        return {
            "root": str(root),
            "applicants_processed": len(results),
            "documents_indexed": sum(
                result["documents"]
                for result in results
            ),
            "chunks_indexed": sum(
                result["chunks"]
                for result in results
            ),
            "results": results,
        }

    def _get_document_type(
        self,
        file_path: Path,
    ) -> str:
        parts = {
            part.lower()
            for part in file_path.parts
        }

        for folder, document_type in (
            self.DOCUMENT_TYPE_MAP.items()
        ):
            if folder in parts:
                return document_type

        return "other"

    def _extract_document_id(
        self,
        file_path: Path,
    ) -> str:
        filename = file_path.stem

        if "_" in filename:
            return filename.split("_", 1)[0]

        return filename


document_indexer = DocumentIndexer()