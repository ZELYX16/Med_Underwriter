from __future__ import annotations

from typing import Any

from app.config import settings
from app.rag.query_classifier import query_classifier
from app.store.vector_store import vector_store


class HybridRAG:
    """
    Main knowledge-retrieval entry point.

    Responsibilities:
    - classify the query
    - route to the correct knowledge source
    - preserve metadata filters
    - normalize retrieval results
    - optionally apply CRAG quality checking
    """

    REGULATORY_COLLECTION = "regulatory"
    UNDERWRITING_COLLECTION = "underwriting"

    def __init__(self) -> None:
        self.top_k = settings.top_k_results

    def _search(
        self,
        collection_name: str,
        query: str,
        top_k: int | None = None,
        where: dict[str, Any] | None = None,
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

        try:
            results = vector_store.query(
                collection_name=collection_name,
                query_text=query,
                n_results=limit,
                where=where,
            )
        except Exception:
            return []

        return self._normalize_results(
            results
        )

    def search_regulatory(
        self,
        query: str,
        jurisdiction: str = "India",
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._search(
            collection_name=self.REGULATORY_COLLECTION,
            query=query,
            top_k=top_k,
            where={
                "jurisdiction": jurisdiction,
            },
        )

    def search_underwriting(
        self,
        query: str,
        product: str | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        where = (
            {"product": product}
            if product
            else None
        )

        return self._search(
            collection_name=self.UNDERWRITING_COLLECTION,
            query=query,
            top_k=top_k,
            where=where,
        )

    async def retrieve(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        top_k: int | None = None,
        use_crag: bool = True,
    ) -> dict[str, Any]:
        """
        Canonical hybrid retrieval entry point.

        Query classification determines which RAG source
        should be searched. CRAG evaluates the retrieved
        evidence and can request corrective retrieval.
        """

        context = context or {}

        classification = query_classifier.classify(
            query=query,
            context=context,
        )

        intent = classification.get(
            "intent",
            "broad",
        )

        confidence = classification.get(
            "confidence",
            0.0,
        )

        limit = max(
            1,
            min(
                top_k or self.top_k,
                20,
            ),
        )

        if use_crag:
            from app.rag.crag import crag

            crag_result = await crag.retrieve(
                query=query,
                intent=intent,
                context=context,
                top_k=limit,
                source_scope="knowledge",
            )

            return {
                "query": query,
                "intent": intent,
                "classification": classification,
                "intent_confidence": confidence,
                "results": crag_result.get(
                    "results",
                    [],
                ),
                "total_results": crag_result.get(
                    "total_results",
                    0,
                ),
                "quality": crag_result.get(
                    "quality",
                    {},
                ),
                "corrected": crag_result.get(
                    "corrected",
                    False,
                ),
                "sources_used": self._sources_for_intent(
                    intent
                ),
            }

        results = self._route_without_crag(
            query=query,
            intent=intent,
            context=context,
            top_k=limit,
        )

        return {
            "query": query,
            "intent": intent,
            "classification": classification,
            "intent_confidence": confidence,
            "results": results,
            "total_results": len(results),
            "quality": {},
            "corrected": False,
            "sources_used": self._sources_for_intent(
                intent
            ),
        }

    def _route_without_crag(
        self,
        query: str,
        intent: str,
        context: dict[str, Any],
        top_k: int,
    ) -> list[dict[str, Any]]:
        product = (
            context.get(
                "submission",
                {},
            ).get("product")
        )

        if intent == "medical":
            return self._medical_search(
                query=query,
                top_k=top_k,
            )

        if intent == "regulatory":
            return self.search_regulatory(
                query=query,
                jurisdiction="India",
                top_k=top_k,
            )

        if intent == "underwriting":
            return self.search_underwriting(
                query=query,
                product=product,
                top_k=top_k,
            )

        if intent == "broad":
            results: list[dict[str, Any]] = []

            results.extend(
                self._medical_search(
                    query=query,
                    top_k=top_k,
                )
            )

            results.extend(
                self.search_regulatory(
                    query=query,
                    jurisdiction="India",
                    top_k=top_k,
                )
            )

            results.extend(
                self.search_underwriting(
                    query=query,
                    product=product,
                    top_k=top_k,
                )
            )

            return self._deduplicate(
                results
            )[:top_k]

        return []

    def _medical_search(
        self,
        query: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            from app.rag.medgraph_rag import medgraph_rag

            results = (
                medgraph_rag.search_medical_knowledge(
                    query=query,
                    top_k=top_k,
                )
            )

            if not isinstance(results, list):
                return []

            return results

        except Exception:
            return []

    @staticmethod
    def _sources_for_intent(
        intent: str,
    ) -> list[str]:
        mapping = {
            "medical": [
                "medical_knowledge",
            ],
            "claims": [
                "applicant_documents",
            ],
            "policy": [
                "applicant_documents",
            ],
            "regulatory": [
                "regulatory",
            ],
            "underwriting": [
                "underwriting",
            ],
            "broad": [
                "medical_knowledge",
                "regulatory",
                "underwriting",
            ],
        }

        return mapping.get(
            intent,
            [],
        )

    @staticmethod
    def _normalize_results(
        results: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(results, dict):
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
                    "document_id": metadata.get(
                        "document_id"
                    ),
                    "source": metadata.get(
                        "source"
                    ),
                    "file_name": metadata.get(
                        "file_name"
                    ),
                    "jurisdiction": metadata.get(
                        "jurisdiction"
                    ),
                    "product": metadata.get(
                        "product"
                    ),
                }
            )

        return normalized

    @staticmethod
    def _deduplicate(
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        unique: list[
            dict[str, Any]
        ] = []

        seen: set[str] = set()

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

            key = (
                result.get("document_id")
                or metadata.get("document_id")
                or result.get("file_name")
                or metadata.get("file_name")
                or result.get(
                    "content",
                    "",
                )[:150]
            )

            if not key:
                key = str(
                    len(unique)
                )

            if key in seen:
                continue

            seen.add(key)
            unique.append(result)

        return unique


hybrid_rag = HybridRAG()