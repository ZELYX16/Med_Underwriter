from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings
from app.store.vector_store import vector_store


class ApplicantRetriever:
    COLLECTION_NAME = "applicant_documents"

    def __init__(self) -> None:
        self.synthetic_data_path = Path(settings.synthetic_data_path)

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
                {key: value}
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
        if not applicant_id or not query.strip():
            return []

        limit = max(
            1,
            min(
                top_k or settings.top_k_results,
                20,
            ),
        )

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
            results,
            applicant_id=applicant_id,
            document_type=document_type,
        )

    def search_by_type(
        self,
        applicant_id: str,
        query: str,
        document_type: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search(
            applicant_id=applicant_id,
            query=query,
            document_type=document_type,
            top_k=top_k,
        )

    def retrieve_medical_evidence(
        self,
        applicant_id: str,
        query: str = (
            "medical examination diagnosis conditions treatment"
        ),
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_by_type(
            applicant_id,
            query,
            "medical",
            top_k,
        )

    def retrieve_claims_evidence(
        self,
        applicant_id: str,
        query: str = (
            "claims hospitalization treatment claim history"
        ),
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_by_type(
            applicant_id,
            query,
            "claims",
            top_k,
        )

    def retrieve_policy_evidence(
        self,
        applicant_id: str,
        query: str = (
            "existing policy coverage sum insured claims policy status"
        ),
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_by_type(
            applicant_id,
            query,
            "policy",
            top_k,
        )

    def retrieve_underwriting_submission(
        self,
        applicant_id: str,
        query: str = (
            "underwriting submission requested product "
            "sum insured declarations"
        ),
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_by_type(
            applicant_id,
            query,
            "underwriting",
            top_k,
        )

    def retrieve_all(
        self,
        applicant_id: str,
        query: str = (
            "applicant underwriting medical claims policy evidence"
        ),
        top_k: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
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
        applicant_id: str | None = None,
        document_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(results, dict):
            return []

        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        distances = results.get("distances", [])

        if documents and isinstance(documents[0], list):
            documents = documents[0]

        if metadatas and isinstance(metadatas[0], list):
            metadatas = metadatas[0]

        if distances and isinstance(distances[0], list):
            distances = distances[0]

        normalized: list[dict[str, Any]] = []

        for index, document in enumerate(documents):
            metadata = (
                metadatas[index]
                if index < len(metadatas)
                and isinstance(metadatas[index], dict)
                else {}
            )

            result_applicant_id = metadata.get(
                "applicant_id"
            )
            result_document_type = metadata.get(
                "document_type"
            )

            if (
                applicant_id
                and result_applicant_id != applicant_id
            ):
                continue

            if (
                document_type
                and result_document_type != document_type
            ):
                continue

            normalized.append(
                {
                    "content": document,
                    "metadata": metadata,
                    "distance": (
                        distances[index]
                        if index < len(distances)
                        else None
                    ),
                    "applicant_id": result_applicant_id,
                    "document_type": result_document_type,
                    "document_id": metadata.get(
                        "document_id"
                    ),
                    "source": metadata.get("source"),
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
        return bool(
            self.search(
                applicant_id,
                query,
                document_type,
                top_k=1,
            )
        )


retriever = ApplicantRetriever()