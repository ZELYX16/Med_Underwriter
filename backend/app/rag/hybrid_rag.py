from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings
from app.store.vector_store import vector_store


class HybridRAG:
    """
    Retrieval layer for insurance and underwriting knowledge.

    Sources are kept separate from medical knowledge so that:
    - IRDAI/regulatory evidence is not mixed with medical evidence.
    - underwriting guidelines are not treated as regulations.
    - retrieved documents can be traced back to their source.
    """

    REGULATORY_COLLECTION = "regulatory_knowledge"
    UNDERWRITING_COLLECTION = "underwriting_knowledge"

    def __init__(self) -> None:
        self.data_root = Path(
            settings.processed_data_path
        )

    def _search_collection(
        self,
        collection_name: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []

        limit = top_k or settings.top_k_results

        try:
            results = vector_store.query(
                collection_name=collection_name,
                query_text=query,
                n_results=limit,
            )
        except Exception:
            return []

        return self._normalize_results(results)

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

        normalized: list[
            dict[str, Any]
        ] = []

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
                    "source": metadata.get(
                        "source",
                        "unknown",
                    ),
                    "file_name": metadata.get(
                        "file_name",
                        "unknown",
                    ),
                }
            )

        return normalized

    def search_regulatory(
        self,
        query: str,
        jurisdiction: str = "India",
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve regulatory evidence.

        For the current demo, India is the primary jurisdiction
        and IRDAI is the preferred regulatory authority.
        """

        regulatory_query = (
            f"Jurisdiction: {jurisdiction}. "
            f"Regulatory authority: IRDAI. "
            f"Query: {query}"
        )

        results = self._search_collection(
            collection_name=self.REGULATORY_COLLECTION,
            query=regulatory_query,
            top_k=top_k,
        )

        return {
            "query": query,
            "jurisdiction": jurisdiction,
            "authority": "IRDAI",
            "results": results,
            "result_count": len(results),
        }

    def search_underwriting(
        self,
        query: str,
        product: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve company/product underwriting guidance.

        These documents are NOT treated as regulatory sources.
        """

        product_context = (
            f" Product: {product}."
            if product
            else ""
        )

        underwriting_query = (
            "Underwriting guidance."
            f"{product_context} "
            f"Query: {query}"
        )

        results = self._search_collection(
            collection_name=self.UNDERWRITING_COLLECTION,
            query=underwriting_query,
            top_k=top_k,
        )

        return {
            "query": query,
            "product": product,
            "results": results,
            "result_count": len(results),
        }

    def retrieve_for_case(
        self,
        query: str,
        jurisdiction: str = "India",
        product: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """
        Perform both regulatory and underwriting retrieval.
        """

        regulatory = self.search_regulatory(
            query=query,
            jurisdiction=jurisdiction,
            top_k=top_k,
        )

        underwriting = self.search_underwriting(
            query=query,
            product=product,
            top_k=top_k,
        )

        return {
            "regulatory": regulatory,
            "underwriting": underwriting,
            "total_results": (
                regulatory["result_count"]
                + underwriting["result_count"]
            ),
        }

    def get_regulatory_sources(
        self,
    ) -> list[dict[str, Any]]:
        """
        Return indexed regulatory documents.
        """

        try:
            return vector_store.get_documents(
                collection_name=self.REGULATORY_COLLECTION
            )
        except Exception:
            return []

    def get_underwriting_sources(
        self,
    ) -> list[dict[str, Any]]:
        """
        Return indexed underwriting documents.
        """

        try:
            return vector_store.get_documents(
                collection_name=self.UNDERWRITING_COLLECTION
            )
        except Exception:
            return []


hybrid_rag = HybridRAG()