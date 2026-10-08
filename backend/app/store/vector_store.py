from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from app.config import settings


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
        embedding = self.embedding_model.encode(
            [query_text],
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

        return embedding[0].tolist()

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
    ) -> dict[str, Any]:
        if not query_text or not query_text.strip():
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }

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

        return collection.query(**kwargs)

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