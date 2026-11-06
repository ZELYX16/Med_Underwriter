from pathlib import Path

from app.config import settings
from app.rag.document_loader import DocumentLoader
from app.store.vector_store import VectorStore


class DataIndexer:
    MEDICAL_COLLECTION = "medical_knowledge"
    REGULATORY_COLLECTION = "regulatory"
    UNDERWRITING_COLLECTION = "underwriting"


    def __init__(self):
        self.loader = DocumentLoader()
        self.vector_store = VectorStore()

    def _load_directory(self, directory: Path) -> list[dict]:
        if not directory.exists():
            print(f"[WARN] Directory not found: {directory}")
            return []

        return self.loader.load_directory(directory)

    def _index(
        self,
        collection_name: str,
        documents: list[dict],
        base_metadata: dict | None = None,
    ) -> int:
        if not documents:
            return 0

        base_metadata = base_metadata or {}

        texts = []
        metadatas = []
        ids = []

        for index, document in enumerate(documents):
            text = document.get("text", "").strip()

            if not text:
                continue

            source_metadata = document.get("metadata", {})
            metadata = {
                **source_metadata,
                **base_metadata,
            }

            texts.append(text)
            metadatas.append(metadata)

            source = source_metadata.get("source", "unknown")
            source_stem = Path(source).stem

            applicant_id = base_metadata.get(
                "applicant_id",
                "global",
            )

            chunk_index = source_metadata.get(
                "chunk_index",
                index,
            )

            document_id = (
                f"{collection_name}:"
                f"{applicant_id}:"
                f"{source_stem}:"
                f"{chunk_index}"
            )

            ids.append(document_id)

        if not texts:
            return 0

        return self.vector_store.add_documents(
            collection_name=collection_name,
            documents=texts,
            metadatas=metadatas,
            ids=ids,
        )

    def index_medical_knowledge(self) -> int:
        """
        Index general medical knowledge.

        Sources:
        - ICD-10
        - RxNorm
        - synthetic medical knowledge
        """

        total = 0

        medical_sources = [
            (
                settings.synthetic_data_directory
                / "evaluation"
                / "medical_knowledge"
            ),
        ]

        for directory in medical_sources:
            documents = self._load_directory(directory)

            count = self._index(
                collection_name=self.MEDICAL_COLLECTION,
                documents=documents,
                base_metadata={
                    "evidence_scope": "knowledge",
                    "knowledge_type": "medical",
                    "source_type": "medical_knowledge",
                },
            )

            total += count

            print(
                f"[MEDICAL] {directory}: "
                f"{count} chunks"
            )

        return total

    def index_regulatory(self) -> int:
        """
        Index official and synthetic regulatory knowledge.

        Sources:
        - official IRDAI documents
        - synthetic regulatory reference
        """

        total = 0

        regulatory_sources = [
            (
                settings.raw_data_directory
                / "regulatory"
                / "irdai",
                {
                    "evidence_scope": "knowledge",
                    "knowledge_type": "regulatory",
                    "source_type": "official_regulatory_source",
                    "jurisdiction": "India",
                    "regulator": "IRDAI",
                },
            ),
            (
                settings.synthetic_data_directory
                / "regulatory",
                {
                    "evidence_scope": "knowledge",
                    "knowledge_type": "regulatory",
                    "source_type": "synthetic_regulatory_reference",
                    "jurisdiction": "India",
                    "regulator": "IRDAI",
                },
            ),
        ]

        for directory, metadata in regulatory_sources:
            documents = self._load_directory(directory)

            count = self._index(
                collection_name=self.REGULATORY_COLLECTION,
                documents=documents,
                base_metadata=metadata,
            )

            total += count

            print(
                f"[REGULATORY] {directory}: "
                f"{count} chunks"
            )

        return total

    def index_underwriting(self) -> int:
        """
        Index underwriting guidance and pricing knowledge.

        Sources:
        - synthetic underwriting guidelines
        - synthetic pricing rules
        """

        total = 0

        underwriting_sources = [
            settings.synthetic_data_directory / "underwriting",
            settings.synthetic_data_directory / "pricing",
        ]

        for directory in underwriting_sources:
            documents = self._load_directory(directory)

            count = self._index(
                collection_name=self.UNDERWRITING_COLLECTION,
                documents=documents,
                base_metadata={
                    "evidence_scope": "knowledge",
                    "knowledge_type": "underwriting",
                    "source_type": "synthetic_underwriting_knowledge",
                },
            )

            total += count

            print(
                f"[UNDERWRITING] {directory}: "
                f"{count} chunks"
            )

        return total

    def run(self) -> None:
        """Index shared knowledge only; applicant files must never enter ChromaDB."""
        print("=" * 60)
        print("MedUnderwrite AI - Shared Knowledge Indexing")
        print("=" * 60)

        print(
            f"ChromaDB path: "
            f"{settings.chroma_directory}"
        )

        print()

        medical_count = self.index_medical_knowledge()

        print()

        regulatory_count = self.index_regulatory()

        print()

        underwriting_count = self.index_underwriting()

        print()
        print("=" * 60)
        print("INDEXING COMPLETE")
        print("=" * 60)

        print(
            f"Medical knowledge  : {medical_count}"
        )
        print(
            f"Regulatory         : {regulatory_count}"
        )
        print(
            f"Underwriting       : {underwriting_count}"
        )

        print("=" * 60)
        print()
        print("ChromaDB collections:")

        collections = self.vector_store.list_collections()

        for collection_name in collections:
            try:
                count = self.vector_store.count(collection_name)
                print(
                    f"  {collection_name}: {count}"
                )
            except Exception as exc:
                print(
                    f"  {collection_name}: "
                    f"count unavailable ({exc})"
                )


if __name__ == "__main__":
    indexer = DataIndexer()
    indexer.run()