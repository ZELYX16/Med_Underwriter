import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from app.config import settings
from app.rag.budget import RetrievalBudget, current_budget


class VectorStore:
    def __init__(self):
        self.persist_directory = Path(
            settings.chroma_directory
        )

        self.persist_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.embedding_model = SentenceTransformer(
            settings.embedding_model
        )

        self.embedding_model.max_seq_length = 256

        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=ChromaSettings(
                anonymized_telemetry=False,
            ),
        )

        # Repeated queries (same text across agents / rescore rounds)
        # skip re-encoding.
        self._query_embeddings: OrderedDict[str, list[float]] = OrderedDict()
        self._embed_lock = threading.Lock()

    def get_collection(self, collection_name: str):
        return self.client.get_or_create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine",
            },
        )

    def list_collections(self) -> list[str]:
        return [
            collection.name
            for collection in self.client.list_collections()
        ]

    def _embed_documents(
        self,
        documents: list[str],
    ) -> list[list[float]]:
        if not documents:
            return []

        embeddings = self.embedding_model.encode(
            documents,
            batch_size=8,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        return embeddings.tolist()

    def _embed_query(
        self,
        query_text: str,
    ) -> list[float]:
        key = query_text.strip()

        with self._embed_lock:
            cached = self._query_embeddings.get(key)
            if cached is not None:
                self._query_embeddings.move_to_end(key)
                return cached

        embedding = self.embedding_model.encode(
            [query_text],
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )[0].tolist()

        with self._embed_lock:
            self._query_embeddings[key] = embedding
            while len(self._query_embeddings) > 512:
                self._query_embeddings.popitem(last=False)

        return embedding

    def warm_query_embeddings(self, queries: list[str]) -> None:
        """Encode several queries in one call and prime the query cache."""
        with self._embed_lock:
            pending = [
                q.strip()
                for q in dict.fromkeys(queries)
                if q and q.strip() and q.strip() not in self._query_embeddings
            ]
        if not pending:
            return

        vectors = self.embedding_model.encode(
            pending,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        with self._embed_lock:
            for text, vector in zip(pending, vectors):
                self._query_embeddings[text] = vector.tolist()
            while len(self._query_embeddings) > 512:
                self._query_embeddings.popitem(last=False)

    def add_documents(
        self,
        collection_name: str,
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> int:
        if not documents:
            return 0

        if metadatas is not None and len(metadatas) != len(documents):
            raise ValueError(
                "metadatas length must match documents length"
            )

        if ids is not None and len(ids) != len(documents):
            raise ValueError(
                "ids length must match documents length"
            )

        collection = self.get_collection(
            collection_name
        )

        if ids is None:
            ids = [
                f"{collection_name}_{index}"
                for index in range(len(documents))
            ]

        embeddings = self._embed_documents(
            documents
        )

        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        return len(documents)

    def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
        filter_relevant: bool = True,
    ) -> dict[str, Any]:
        empty = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

        if not query_text or not query_text.strip():
            return empty

        # Case-level retrieval budget (see app/rag/budget.py)
        budget = current_budget()
        if budget is not None and not budget.try_acquire():
            return empty

        collection = self.get_collection(
            collection_name
        )

        collection_count = collection.count()

        if collection_count == 0:
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }

        query_embedding = self._embed_query(
            query_text
        )

        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(
                n_results,
                collection_count,
            ),
        }

        if where:
            kwargs["where"] = where

        raw = collection.query(**kwargs)

        if not filter_relevant:
            return raw

        return self._filter_relevant(raw, budget)

    @staticmethod
    def _filter_relevant(
        raw: dict[str, Any],
        budget: RetrievalBudget | None,
    ) -> dict[str, Any]:
        """
        Drop weak matches: beyond the absolute distance ceiling, or far
        behind the best hit. Trim chunk text and respect the case's
        remaining chunk budget.
        """
        try:
            distances = (raw.get("distances") or [[]])[0]
            if not distances:
                return raw

            best = min(distances)
            ceiling = min(
                settings.retrieval_max_distance,
                best + settings.retrieval_relative_margin,
            )
            keep = [
                i for i, d in enumerate(distances) if d <= ceiling
            ][: settings.retrieval_per_source_k]

            if budget is not None:
                keep = keep[: budget.remaining_chunks()]
                budget.record_chunks(len(keep))

            limit = settings.retrieval_chunk_chars
            result: dict[str, Any] = {}
            for key, value in raw.items():
                if (
                    isinstance(value, list)
                    and value
                    and isinstance(value[0], list)
                ):
                    rows = [value[0][i] for i in keep]
                    if key == "documents":
                        rows = [
                            r[:limit] if isinstance(r, str) else r
                            for r in rows
                        ]
                    result[key] = [rows]
                else:
                    result[key] = value
            return result
        except Exception:
            return raw

    def get_documents(
        self,
        collection_name: str,
        where: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        collection = self.get_collection(
            collection_name
        )

        kwargs: dict[str, Any] = {
            "limit": limit,
        }

        if where:
            kwargs["where"] = where

        return collection.get(**kwargs)

    def count(
        self,
        collection_name: str,
    ) -> int:
        collection = self.get_collection(
            collection_name
        )

        return collection.count()

    def health_check(self) -> dict[str, Any]:
        try:
            collections = self.list_collections()

            return {
                "status": "healthy",
                "persist_directory": str(
                    self.persist_directory
                ),
                "collections": collections,
            }

        except Exception as exc:
            return {
                "status": "unhealthy",
                "error": str(exc),
            }


vector_store = VectorStore()