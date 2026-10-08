from pathlib import Path

from app.config import settings
from app.rag.document_loader import DocumentLoader
from app.store.vector_store import VectorStore


class DataIndexer:
    APPLICANT_COLLECTION = "applicant_documents"
    MEDICAL_COLLECTION = "medical_knowledge"
    REGULATORY_COLLECTION = "regulatory"
    UNDERWRITING_COLLECTION = "underwriting"

    DOCUMENT_TYPE_MAP = {
        "medical": "medical",
        "claims": "claims",
        "policy": "policy",
        "underwriting": "underwriting",
    }

    def __init__(self):
        self.loader = DocumentLoader()
        self.vector_store = VectorStore()

    def _load_directory(self, directory: Path) -> list[dict]:
        if not directory.exists():
            print(f"[WARN] Directory not found: {directory}")
            return []

        return self.loader.load_directory(directory)

    def _infer_document_type(self, source: str) -> str:
        """
        Infer applicant document type from its directory structure.

        Example:
        data/synthetic/applicants/APP-TEST-001/medical/file.pdf
        -> medical
        """
        parts = {part.lower() for part in Path(source).parts}

        for folder_name, document_type in self.DOCUMENT_TYPE_MAP.items():
            if folder_name in parts:
                return document_type

        return "unknown"

    def _index(
        self,
        collection_name: str,
        documents: list[dict],
        base_metadata: dict | None = None,
        infer_document_type: bool = False,
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

            if infer_document_type:
                source = source_metadata.get("source", "")
                document_type = self._infer_document_type(source)

                if document_type == "unknown":
                    print(
                        f"[WARN] Unknown applicant document type: "
                        f"{source}"
                    )
                    continue

                metadata["document_type"] = document_type

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

    def index_applicants(self) -> int:
        """
        Index applicant-specific evidence.

        Expected structure:

        data/synthetic/applicants/
        ├── APP-TEST-001/
        │   ├── medical/
        │   ├── policy/
        │   └── underwriting/
        └── APP-TEST-002/
            ├── medical/
            ├── claims/
            ├── policy/
            └── underwriting/
        """
        applicants_root = (
            settings.synthetic_data_directory / "applicants"
        )

        if not applicants_root.exists():
            print(f"[WARN] Applicant directory not found: {applicants_root}")
            return 0

        total = 0

        applicant_directories = sorted(
            path
            for path in applicants_root.iterdir()
            if path.is_dir()
        )

        for applicant_directory in applicant_directories:
            applicant_id = applicant_directory.name

            documents = self._load_directory(applicant_directory)

            count = self._index(
                collection_name=self.APPLICANT_COLLECTION,
                documents=documents,
                base_metadata={
                    "applicant_id": applicant_id,
                    "case_id": f"UW-{applicant_id.replace('APP-', '')}",
                    "evidence_scope": "applicant",
                    "source_type": "synthetic_applicant_document",
                },
                infer_document_type=True,
            )

            total += count

            print(
                f"[APPLICANT] {applicant_id}: "
                f"{count} chunks"
            )

        return total

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
        print("=" * 60)
        print("MedUnderwrite AI - ChromaDB Indexing")
        print("=" * 60)

        print(
            f"ChromaDB path: "
            f"{settings.chroma_directory}"
        )

        print()

        applicant_count = self.index_applicants()

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
            f"Applicant evidence : {applicant_count}"
        )
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