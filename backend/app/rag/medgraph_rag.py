from __future__ import annotations

import re
from typing import Any

from app.config import settings
from app.store.vector_store import vector_store


class MedGraphRAG:
    """
    Medical Graph RAG.

    Uses two retrieval paths:

    1. Top-down:
       Exact ICD-10 / SNOMED / concept metadata matching.

    2. Bottom-up:
       Semantic retrieval followed by graph-context enrichment.

    This layer contains medical knowledge only.
    Regulatory and underwriting knowledge remain separate.
    """

    COLLECTION_NAME = "medical_knowledge"

    CODE_PATTERNS = [
        re.compile(
            r"\b[A-Z]\d{2}(?:\.\d{1,4})?\b"
        ),
    ]

    def __init__(self) -> None:
        self.top_k = settings.top_k_results

    def search_medical_knowledge(
        self,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        if not query or not query.strip():
            return []

        limit = max(
            1,
            min(
                top_k or self.top_k,
                20,
            ),
        )

        exact_results = self._exact_code_search(
            query=query,
            top_k=limit,
        )

        semantic_results = self._semantic_search(
            query=query,
            top_k=limit,
        )

        combined = self._merge_results(
            exact_results,
            semantic_results,
        )

        return self._enrich_graph_context(
            combined[:limit]
        )

    def search(
        self,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.search_medical_knowledge(
            query=query,
            top_k=top_k,
        )

    def retrieve_for_applicant(
        self,
        applicant_profile: dict[str, Any],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        queries = self._build_applicant_queries(
            applicant_profile
        )

        limit = max(
            1,
            min(
                top_k or self.top_k,
                20,
            ),
        )

        combined: list[
            dict[str, Any]
        ] = []

        seen: set[str] = set()

        for query in queries:
            results = self.search_medical_knowledge(
                query=query,
                top_k=limit,
            )

            for result in results:
                key = self._result_key(
                    result
                )

                if key in seen:
                    continue

                seen.add(key)
                combined.append(result)

                if len(combined) >= limit:
                    return combined[:limit]

        return combined[:limit]

    def _exact_code_search(
        self,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        codes = self._extract_codes(
            query
        )

        if not codes:
            return []

        results: list[
            dict[str, Any]
        ] = []

        for code in codes:
            for metadata_filter in (
                {
                    "code": code,
                },
                {
                    "concept_id": code,
                },
            ):
                try:
                    raw = vector_store.query(
                        collection_name=(
                            self.COLLECTION_NAME
                        ),
                        query_text=query,
                        n_results=top_k,
                        where=metadata_filter,
                    )

                except Exception:
                    continue

                results.extend(
                    self._normalize_results(
                        raw
                    )
                )

        return self._deduplicate(
            results
        )

    def _semantic_search(
        self,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            results = vector_store.query(
                collection_name=(
                    self.COLLECTION_NAME
                ),
                query_text=query,
                n_results=top_k,
            )

        except Exception:
            return []

        return self._normalize_results(
            results
        )

    def _build_applicant_queries(
        self,
        applicant_profile: dict[str, Any],
    ) -> list[str]:
        conditions = applicant_profile.get(
            "medical_conditions",
            [],
        )

        medications = applicant_profile.get(
            "medications",
            [],
        )

        queries: list[str] = []

        if conditions:
            queries.append(
                "medical conditions "
                + " ".join(
                    str(condition)
                    for condition in conditions
                )
            )

            queries.extend(
                str(condition)
                for condition in conditions
                if str(condition).strip()
            )

        if medications:
            queries.append(
                "medications "
                + " ".join(
                    str(medication)
                    for medication in medications
                )
            )

            queries.extend(
                str(medication)
                for medication in medications
                if str(medication).strip()
            )

        if not queries:
            queries.append(
                "medical conditions "
                "diagnosis treatment "
                "comorbidity medication"
            )

        return [
            query.strip()
            for query in queries
            if query.strip()
        ]

    @staticmethod
    def _extract_codes(
        query: str,
    ) -> list[str]:
        codes: list[str] = []

        for pattern in MedGraphRAG.CODE_PATTERNS:
            for match in pattern.findall(query):
                normalized = str(match).upper()

                if normalized not in codes:
                    codes.append(normalized)

        return codes

    @staticmethod
    def _merge_results(
        exact_results: list[
            dict[str, Any]
        ],
        semantic_results: list[
            dict[str, Any]
        ],
    ) -> list[dict[str, Any]]:
        return MedGraphRAG._deduplicate(
            exact_results
            + semantic_results
        )

    @staticmethod
    def _enrich_graph_context(
        results: list[
            dict[str, Any]
        ],
    ) -> list[dict[str, Any]]:
        enriched: list[
            dict[str, Any]
        ] = []

        for result in results:
            metadata = result.get(
                "metadata",
                {},
            )

            if not isinstance(
                metadata,
                dict,
            ):
                metadata = {}

            graph_context = {
                "concept_id": metadata.get(
                    "concept_id"
                ),
                "concept_type": metadata.get(
                    "concept_type"
                ),
                "code_system": metadata.get(
                    "code_system"
                ),
                "code": metadata.get(
                    "code"
                ),
                "related_concepts": (
                    metadata.get(
                        "related_concepts",
                        [],
                    )
                ),
                "relationships": (
                    metadata.get(
                        "relationships",
                        [],
                    )
                ),
            }

            enriched.append(
                {
                    **result,
                    "graph_context": (
                        graph_context
                    ),
                }
            )

        return enriched

    @staticmethod
    def _normalize_results(
        results: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(
            results,
            dict,
        ):
            return []

        documents = results.get(
            "documents",
            [],
        )

        metadatas = results.get(
            "metadatas",
            [],
        )

        distances = results.get(
            "distances",
            [],
        )

        if documents and isinstance(
            documents[0],
            list,
        ):
            documents = documents[0]

        if metadatas and isinstance(
            metadatas[0],
            list,
        ):
            metadatas = metadatas[0]

        if distances and isinstance(
            distances[0],
            list,
        ):
            distances = distances[0]

        normalized: list[
            dict[str, Any]
        ] = []

        for index, document in enumerate(
            documents
        ):
            metadata = (
                metadatas[index]
                if index < len(metadatas)
                and isinstance(
                    metadatas[index],
                    dict,
                )
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
                    "metadata": metadata,
                    "distance": distance,
                    "document_id": (
                        metadata.get(
                            "document_id"
                        )
                    ),
                    "source": metadata.get(
                        "source"
                    ),
                    "file_name": metadata.get(
                        "file_name"
                    ),
                    "concept_id": (
                        metadata.get(
                            "concept_id"
                        )
                    ),
                    "concept_type": (
                        metadata.get(
                            "concept_type"
                        )
                    ),
                    "code_system": (
                        metadata.get(
                            "code_system"
                        )
                    ),
                    "code": metadata.get(
                        "code"
                    ),
                }
            )

        return normalized

    @staticmethod
    def _result_key(
        result: dict[str, Any],
    ) -> str:
        metadata = result.get(
            "metadata",
            {},
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

        return str(
            result.get("document_id")
            or metadata.get(
                "document_id"
            )
            or result.get("file_name")
            or metadata.get(
                "file_name"
            )
            or result.get(
                "content",
                "",
            )[:150]
        )

    @staticmethod
    def _deduplicate(
        results: list[
            dict[str, Any]
        ],
    ) -> list[dict[str, Any]]:
        unique: list[
            dict[str, Any]
        ] = []

        seen: set[str] = set()

        for result in results:
            key = (
                MedGraphRAG._result_key(
                    result
                )
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(result)

        return unique


medgraph_rag = MedGraphRAG()