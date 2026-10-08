from __future__ import annotations

import shutil
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.config import settings
from app.store.state_store import StateStore


CHROMA_COLLECTIONS = [
    "applicant_documents",
    "medical_knowledge",
    "regulatory",
    "underwriting",
]


def print_header(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def reset_sqlite() -> None:
    print_header("1. RESET SQLITE DATABASE")

    database_path = Path(settings.sqlite_file)

    print(f"Database: {database_path}")

    if database_path.exists():
        database_path.unlink()
        print("[OK] SQLite database deleted.")
    else:
        print("[INFO] SQLite database did not exist.")

    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{database_path}{suffix}")

        if sidecar.exists():
            sidecar.unlink()
            print(f"[OK] Removed {sidecar.name}")

    StateStore(database_path)

    print("[OK] SQLite schema recreated.")


def reset_chroma() -> None:
    print_header("2. RESET CHROMADB")

    chroma_directory = Path(
        settings.chroma_directory
    ).resolve()

    print(
        f"Chroma directory: "
        f"{chroma_directory}"
    )

    if chroma_directory.exists():
        shutil.rmtree(chroma_directory)

        print(
            "[OK] Chroma directory deleted."
        )
    else:
        print(
            "[INFO] Chroma directory did not exist."
        )

    chroma_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "[OK] Chroma directory recreated."
    )


def seed_database() -> None:
    print_header("3. SEED SYNTHETIC DATABASE")

    # Import only after SQLite reset.
    from app.services.seed_database import seed

    seed()

    print(
        "[OK] Synthetic applicants and cases seeded."
    )


def index_data() -> None:
    print_header("4. INDEX VECTOR DATA")

    # IMPORTANT:
    # DataIndexer imports VectorStore.
    # Therefore this import must happen AFTER
    # the Chroma directory has been completely reset.
    from app.services.index_data import DataIndexer

    indexer = DataIndexer()

    applicant_count = indexer.index_applicants()

    medical_count = (
        indexer.index_medical_knowledge()
    )

    regulatory_count = (
        indexer.index_regulatory()
    )

    underwriting_count = (
        indexer.index_underwriting()
    )

    print()
    print("Indexing summary:")
    print(
        f"  Applicant evidence : "
        f"{applicant_count}"
    )
    print(
        f"  Medical knowledge  : "
        f"{medical_count}"
    )
    print(
        f"  Regulatory         : "
        f"{regulatory_count}"
    )
    print(
        f"  Underwriting       : "
        f"{underwriting_count}"
    )


def verify_database() -> None:
    print_header("5. VERIFY SQLITE DATABASE")

    state_store = StateStore()

    applicants = state_store.list_applicants(
        limit=1000
    )

    cases = state_store.list_cases(
        limit=1000
    )

    print(
        f"Applicants : {len(applicants)}"
    )

    print(
        f"Cases      : {len(cases)}"
    )

    if not applicants:
        raise RuntimeError(
            "No applicants were seeded."
        )

    if not cases:
        raise RuntimeError(
            "No underwriting cases were seeded."
        )

    print(
        "[OK] SQLite verification passed."
    )


def verify_chroma() -> None:
    print_header("6. VERIFY CHROMADB")

    # Reuse the VectorStore instance that was
    # created by DataIndexer. This avoids creating
    # another PersistentClient with different settings.
    from app.store.vector_store import vector_store

    client = vector_store.client

    collections = client.list_collections()

    collection_names = set()

    for collection in collections:
        name = getattr(
            collection,
            "name",
            None,
        )

        if name:
            collection_names.add(name)

    print(
        f"Collections found: "
        f"{sorted(collection_names)}"
    )

    for collection_name in CHROMA_COLLECTIONS:
        if collection_name in collection_names:
            collection = client.get_collection(
                name=collection_name
            )

            count = collection.count()

            print(
                f"  {collection_name:<24} "
                f"{count} chunks"
            )
        else:
            print(
                f"  {collection_name:<24} "
                f"NOT FOUND"
            )

    if "applicant_documents" not in collection_names:
        raise RuntimeError(
            "Applicant evidence collection "
            "was not created."
        )

    if "medical_knowledge" not in collection_names:
        raise RuntimeError(
            "Medical knowledge collection "
            "was not created."
        )

    if "regulatory" not in collection_names:
        raise RuntimeError(
            "Regulatory collection "
            "was not created."
        )

    if "underwriting" not in collection_names:
        raise RuntimeError(
            "Underwriting collection "
            "was not created."
        )

    applicant_count = client.get_collection(
        name="applicant_documents"
    ).count()

    medical_count = client.get_collection(
        name="medical_knowledge"
    ).count()

    regulatory_count = client.get_collection(
        name="regulatory"
    ).count()

    underwriting_count = client.get_collection(
        name="underwriting"
    ).count()

    if applicant_count == 0:
        raise RuntimeError(
            "Applicant evidence collection is empty."
        )

    if medical_count == 0:
        raise RuntimeError(
            "Medical knowledge collection is empty."
        )

    if regulatory_count == 0:
        raise RuntimeError(
            "Regulatory collection is empty."
        )

    if underwriting_count == 0:
        raise RuntimeError(
            "Underwriting collection is empty."
        )

    print(
        "[OK] Chroma verification passed."
    )


def main() -> None:
    print_header(
        "MEDUNDERWRITE AI — RESET & INITIALIZE"
    )

    print(
        "This will delete the current SQLite "
        "database and Chroma database."
    )

    print(
        "Synthetic source documents will NOT "
        "be deleted."
    )

    confirmation = input(
        "\nType RESET to continue: "
    ).strip()

    if confirmation != "RESET":
        print("Reset cancelled.")
        return

    try:
        # IMPORTANT ORDER
        reset_sqlite()
        reset_chroma()

        # Only now import modules that initialize
        # application state / Chroma.
        seed_database()
        index_data()

        verify_database()
        verify_chroma()

        print_header(
            "INITIALIZATION COMPLETE"
        )

        print(
            "MedUnderwrite AI is ready."
        )

    except Exception as exc:
        print_header(
            "INITIALIZATION FAILED"
        )

        print(
            f"[ERROR] {type(exc).__name__}: "
            f"{exc}"
        )

        raise


if __name__ == "__main__":
    main()