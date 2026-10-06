from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings
from app.store.vector_store import vector_store


class ApplicantRetriever:
    """
    Retrieves applicant-specific evidence from the vector store.

    The retriever keeps applicant filtering separate from the
    higher-level RAG strategies.
    """

    COLLECTION_NAME = "applicant_documents"

    def __init__(self) -> None:
        self.synthetic_data_path = Path(
            settings.synthetic_data_path
        )

    def _build_filter(
        self,
        applicant_id: str,
        document_type: str | None = None,
    ) -> dict[str, Any]:
        filters: dict[str, Any] = {
            "applicant_id": applicant_id,
        }

        if document_type:
            filters["document_type"] = document_type

        if len(filters) == 1:
            return filters

        return {
            "$and": [
                {
                    key: value
                }
                for key, value in filters.items()
            ]
        }

    def search(
        self,
        applicant_id: str,
        query: str,
        document_type: str | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search applicant documents using semantic similarity.
        """

        if not applicant_id:
            return []

        if not query.strip():
            return []

        limit = top_k or settings.top_k_results

        where = self._build_filter(
            applicant_id=applicant_id,
            document_type=document_type,
        )

        try:
            results = vector_store.query(
                collection_name=self.COLLECTION_NAME,
                query_text=query,
                n_results=limit,
                where=where,
            )
        except Exception:
            return []

        return self._normalize_results(
            results
        )

    def search_by_type(
        self,
        applicant_id: str,
        query: str,
        document_type: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search only one type of applicant evidence.

        Supported types can include:
        - medical
        - claim
        - policy
        - underwriting
        """

        return self.search(
            applicant_id=applicant_id,
            query=query,
            document_type=document_type,
            top_k=top_k,
        )

    def retrieve_medical_evidence(
        self,
        applicant_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_by_type(
            applicant_id=applicant_id,
            query=query,
            document_type="medical",
            top_k=top_k,
        )

    def retrieve_claims_evidence(
        self,
        applicant_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_by_type(
            applicant_id=applicant_id,
            query=query,
            document_type="claim",
            top_k=top_k,
        )

    def retrieve_policy_evidence(
        self,
        applicant_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_by_type(
            applicant_id=applicant_id,
            query=query,
            document_type="policy",
            top_k=top_k,
        )

    def retrieve_underwriting_submission(
        self,
        applicant_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_by_type(
            applicant_id=applicant_id,
            query=query,
            document_type="underwriting",
            top_k=top_k,
        )

    def retrieve_all(
        self,
        applicant_id: str,
        query: str,
        top_k: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Retrieve evidence from each applicant document category.
        """

        return {
            "medical": self.retrieve_medical_evidence(
                applicant_id,
                query,
                top_k,
            ),
            "claims": self.retrieve_claims_evidence(
                applicant_id,
                query,
                top_k,
            ),
            "policy": self.retrieve_policy_evidence(
                applicant_id,
                query,
                top_k,
            ),
            "underwriting": self.retrieve_underwriting_submission(
                applicant_id,
                query,
                top_k,
            ),
        }

    def _normalize_results(
        self,
        results: Any,
    ) -> list[dict[str, Any]]:
        if not results:
            return []

        documents = results.get(
            "documents",
            [[]],
        )

        metadatas = results.get(
            "metadatas",
            [[]],
        )

        distances = results.get(
            "distances",
            [[]],
        )

        documents = (
            documents[0]
            if documents
            else []
        )

        metadatas = (
            metadatas[0]
            if metadatas
            else []
        )

        distances = (
            distances[0]
            if distances
            else []
        )

        normalized = []

        for index, document in enumerate(
            documents
        ):
            metadata = (
                metadatas[index]
                if index < len(metadatas)
                else {}
            )

            distance = (
                distances[index]
                if index < len(distances)
                else None
            )

            normalized.append(
                {
                    "content": document,
                    "metadata": metadata or {},
                    "distance": distance,
                    "applicant_id": metadata.get(
                        "applicant_id"
                    ),
                    "document_type": metadata.get(
                        "document_type"
                    ),
                    "document_id": metadata.get(
                        "document_id"
                    ),
                    "source": metadata.get(
                        "source"
                    ),
                    "file_name": metadata.get(
                        "file_name"
                    ),
                }
            )

        return normalized

    def has_evidence(
        self,
        applicant_id: str,
        query: str,
        document_type: str | None = None,
    ) -> bool:
        results = self.search(
            applicant_id=applicant_id,
            query=query,
            document_type=document_type,
            top_k=1,
        )

        return len(results) > 0


retriever = ApplicantRetriever()