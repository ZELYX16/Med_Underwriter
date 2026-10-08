from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb

from app.config import settings


COLLECTIONS = {
    "patient_records": "Patient-level medical records and clinical evidence.",
    "claims_data": "Insurance claims and utilization evidence.",
    "policy_documents": "Policy wording and policy-specific evidence.",
    "regulatory": "Regulatory and compliance documents.",
    "underwriting": "Underwriting guidelines and business rules.",
    "medical_knowledge": "Medical knowledge including ICD-10, RxNorm and clinical concepts.",
}


class ChromaSetup:
    """Centralized ChromaDB initialization and collection management."""

    def __init__(self, persist_directory: str | Path | None = None) -> None:
        self.persist_directory = Path(
            persist_directory or settings.chroma_directory
        ).resolve()

        self.persist_directory.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory)
        )

    def get_or_create_collection(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
    ):
        collection_metadata = metadata or {
            "hnsw:space": "cosine",
        }

        return self.client.get_or_create_collection(
            name=name,
            metadata=collection_metadata,
        )

    def initialize_collections(self) -> dict[str, Any]:
        collections: dict[str, Any] = {}

        for name, description in COLLECTIONS.items():
            collections[name] = self.get_or_create_collection(
                name=name,
                metadata={
                    "description": description,
                    "hnsw:space": "cosine",
                },
            )

        return collections

    def get_collection(self, name: str):
        if name not in COLLECTIONS:
            raise ValueError(
                f"Unknown Chroma collection '{name}'. "
                f"Available collections: {', '.join(COLLECTIONS)}"
            )

        return self.client.get_collection(name=name)

    def collection_exists(self, name: str) -> bool:
        try:
            self.client.get_collection(name=name)
            return True
        except Exception:
            return False

    def list_collections(self) -> list[str]:
        collections = self.client.list_collections()

        names: list[str] = []

        for collection in collections:
            name = getattr(collection, "name", None)

            if name:
                names.append(name)

        return sorted(names)

    def collection_count(self, name: str) -> int:
        collection = self.get_collection(name)
        return collection.count()

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}

        for name in self.list_collections():
            try:
                result[name] = self.collection_count(name)
            except Exception:
                result[name] = 0

        return result

    def reset_collection(self, name: str) -> None:
        if not self.collection_exists(name):
            return

        self.client.delete_collection(name=name)

        self.get_or_create_collection(
            name=name,
            metadata={
                "description": COLLECTIONS.get(name, ""),
                "hnsw:space": "cosine",
            },
        )

    def delete_collection(self, name: str) -> None:
        if self.collection_exists(name):
            self.client.delete_collection(name=name)

    def health_check(self) -> dict[str, Any]:
        try:
            collections = self.list_collections()

            return {
                "status": "healthy",
                "persist_directory": str(self.persist_directory),
                "collections": collections,
                "counts": self.counts(),
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "persist_directory": str(self.persist_directory),
                "error": str(exc),
            }


chroma_setup = ChromaSetup()

# Create the standard collections when the application starts importing
# this module. Existing collections are preserved.
chroma_setup.initialize_collections()