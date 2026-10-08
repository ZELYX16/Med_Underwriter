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
                    "document_id": metadata.get("document_id"),
                    "source": metadata.get("source"),
                    "file_name": (
                        metadata.get("file_name")
                        or metadata.get("filename")
                        or metadata.get("source")
                    ),
                    "filename": (
                        metadata.get("filename")
                        or metadata.get("file_name")
                        or metadata.get("source")
                    ),
                    "title": (
                        metadata.get("title")
                        or metadata.get("filename")
                        or metadata.get("file_name")
                        or metadata.get("source")
                    ),
                    "evidence_scope": metadata.get(
                        "evidence_scope",
                        "applicant",
                    ),
                }
            )

        return normalized

    def group_by_document(
        self,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Convert retrieved chunks into document-level evidence records.

        The UI can use this to show one readable evidence item per source
        document instead of exposing vector-search chunk boundaries.
        """
        groups: dict[str, dict[str, Any]] = {}

        for item in results:
            if not isinstance(item, dict):
                continue

            metadata = item.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}

            document_id = (
                item.get("document_id")
                or metadata.get("document_id")
                or item.get("filename")
                or item.get("file_name")
                or item.get("source")
                or "evidence"
            )
            key = str(document_id)

            group = groups.setdefault(
                key,
                {
                    "document_id": item.get("document_id"),
                    "filename": (
                        item.get("filename")
                        or item.get("file_name")
                        or metadata.get("filename")
                        or metadata.get("file_name")
                        or "Evidence document"
                    ),
                    "document_type": (
                        item.get("document_type")
                        or metadata.get("document_type")
                    ),
                    "applicant_id": (
                        item.get("applicant_id")
                        or metadata.get("applicant_id")
                    ),
                    "source": (
                        item.get("source")
                        or metadata.get("source")
                    ),
                    "evidence_scope": (
                        item.get("evidence_scope")
                        or metadata.get("evidence_scope")
                        or "applicant"
                    ),
                    "contents": [],
                    "metadata": metadata,
                },
            )

            content = item.get("content")
            if content:
                group["contents"].append(str(content).strip())

        grouped = []
        for group in groups.values():
            seen: set[str] = set()
            contents = []
            for content in group["contents"]:
                if content and content not in seen:
                    seen.add(content)
                    contents.append(content)

            group["content"] = "\n\n".join(contents)
            group["chunk_count"] = len(contents)
            group.pop("contents", None)
            grouped.append(group)

        return grouped

    def retrieve_document_views(
        self,
        applicant_id: str,
        query: str,
        document_type: str | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return document-level readable evidence for UI/review layers."""
        return self.group_by_document(
            self.search(
                applicant_id=applicant_id,
                query=query,
                document_type=document_type,
                top_k=top_k,
            )
        )

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