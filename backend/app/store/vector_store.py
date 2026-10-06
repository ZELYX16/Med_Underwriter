from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from app.config import settings


class VectorStore:
    def __init__(
        self,
        persist_path: str | Path | None = None,
        embedding_model: str | None = None,
    ):
        self.persist_path = Path(
            persist_path or settings.chroma_path
        )

        if not self.persist_path.is_absolute():
            self.persist_path = (
                settings.base_path / self.persist_path
            )

        self.persist_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.embedding_model = (
            embedding_model or settings.embedding_model
        )

        self.client = chromadb.PersistentClient(
            path=str(self.persist_path)
        )

        self.embedding_function = (
            SentenceTransformerEmbeddingFunction(
                model_name=self.embedding_model
            )
        )

    def get_or_create_collection(
        self,
        name: str,
    ):
        return self.client.get_or_create_collection(
            name=name,
            embedding_function=self.embedding_function,
        )

    def add_documents(
        self,
        collection_name: str,
        documents: list[str],
        ids: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        if not documents:
            return

        if len(documents) != len(ids):
            raise ValueError(
                "documents and ids must have the same length."
            )

        if metadatas and len(metadatas) != len(documents):
            raise ValueError(
                "metadatas and documents must have the same length."
            )

        collection = self.get_or_create_collection(
            collection_name
        )

        collection.upsert(
            documents=documents,
            ids=ids,
            metadatas=metadatas,
        )

    def query(
        self,
        collection_name: str,
        query: str,
        top_k: int | None = None,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        collection = self.get_or_create_collection(
            collection_name
        )

        count = collection.count()

        if count == 0:
            return []

        requested_k = top_k or settings.top_k_results
        n_results = min(requested_k, count)

        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=[
                "documents",
                "metadatas",
                "distances",
            ],
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        ids = results.get("ids", [[]])[0]

        output = []

        for index, document in enumerate(documents):
            output.append(
                {
                    "id": ids[index] if index < len(ids) else None,
                    "document": document,
                    "metadata": (
                        metadatas[index]
                        if index < len(metadatas)
                        else {}
                    ),
                    "distance": (
                        distances[index]
                        if index < len(distances)
                        else None
                    ),
                }
            )

        return output

    def get_documents(
        self,
        collection_name: str,
        ids: list[str] | None = None,
    ) -> dict[str, Any]:
        collection = self.get_or_create_collection(
            collection_name
        )

        if ids:
            return collection.get(
                ids=ids,
                include=[
                    "documents",
                    "metadatas",
                ],
            )

        return collection.get(
            include=[
                "documents",
                "metadatas",
            ],
        )

    def delete_documents(
        self,
        collection_name: str,
        ids: list[str],
    ) -> None:
        if not ids:
            return

        collection = self.get_or_create_collection(
            collection_name
        )

        collection.delete(ids=ids)

    def delete_collection(
        self,
        collection_name: str,
    ) -> None:
        try:
            self.client.delete_collection(
                name=collection_name
            )
        except Exception:
            pass

    def list_collections(self) -> list[str]:
        collections = self.client.list_collections()
        return [collection.name for collection in collections]


vector_store = VectorStore()