"""
MedUnderwrite AI — ChromaDB Setup & Collection Management

Creates / retrieves the 5 ChromaDB collections and provides:
  - A singleton client (local PersistentClient or HTTP client for Docker/cloud)
  - Helper to test queries per collection
  - Health check returning document counts per collection
"""
from __future__ import annotations

import logging
from typing import Optional

import chromadb
from chromadb import Collection
from chromadb.utils import embedding_functions

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# Collection names — single source of truth
# ---------------------------------------------------------------------------
COLLECTIONS: dict[str, dict] = {
    "patient_records": {
        "description": "MIMIC-IV patient records with ICD-10 codes and EHR summaries",
        "metadata": {"hnsw:space": "cosine"},
    },
    "claims_data": {
        "description": "CMS SynPUFs 3-year claims history",
        "metadata": {"hnsw:space": "cosine"},
    },
    "medical_knowledge": {
        "description": "MedRAG knowledge graph — ICD-10/SNOMED entries, comorbidities, guidelines",
        "metadata": {"hnsw:space": "cosine"},
    },
    "policy_documents": {
        "description": "Underwriting policy templates and coverage rules",
        "metadata": {"hnsw:space": "cosine"},
    },
    "underwriting_guidelines": {
        "description": "Actuarial benchmarks, pricing tables, UW decision rules",
        "metadata": {"hnsw:space": "cosine"},
    },
}

# ---------------------------------------------------------------------------
# Embedding function — all-MiniLM-L6-v2 (local, no API cost)
# ---------------------------------------------------------------------------
_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------
_client: Optional[chromadb.ClientAPI] = None


def get_chroma_client() -> chromadb.ClientAPI:
    """
    Return a cached ChromaDB client.
    - local  → PersistentClient (file-based, no server needed)
    - docker / cloud → HttpClient pointing at the ChromaDB container
    """
    global _client
    if _client is not None:
        return _client

    if settings.chroma_client_mode == "persistent":
        logger.info("ChromaDB: using PersistentClient at %s", settings.chroma_path)
        _client = chromadb.PersistentClient(path=settings.chroma_path)
    else:
        logger.info(
            "ChromaDB: using HttpClient at %s:%s",
            settings.chroma_host,
            settings.chroma_port,
        )
        _client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )

    return _client


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def get_or_create_collection(name: str) -> Collection:
    """
    Get an existing ChromaDB collection or create it with the standard
    embedding function and metadata.

    Args:
        name: Must be one of the keys in COLLECTIONS.

    Returns:
        ChromaDB Collection object.
    """
    if name not in COLLECTIONS:
        raise ValueError(f"Unknown collection '{name}'. Valid: {list(COLLECTIONS)}")

    client = get_chroma_client()
    col_meta = COLLECTIONS[name]

    collection = client.get_or_create_collection(
        name=name,
        embedding_function=_embedding_fn,
        metadata=col_meta["metadata"],
    )
    logger.debug("Collection '%s' ready (count=%d)", name, collection.count())
    return collection


def get_all_collections() -> dict[str, Collection]:
    """Initialise and return all 5 collections."""
    return {name: get_or_create_collection(name) for name in COLLECTIONS}


def test_query(collection_name: str, query_text: str, n_results: int = 3) -> dict:
    """
    Run a test semantic query against a collection.

    Args:
        collection_name: Name of the collection to query.
        query_text: Free-text query string.
        n_results: Number of results to return.

    Returns:
        Dict with 'ids', 'documents', 'distances' lists.
    """
    col = get_or_create_collection(collection_name)
    results = col.query(
        query_texts=[query_text],
        n_results=min(n_results, col.count()) if col.count() > 0 else 0,
    )
    return {
        "collection": collection_name,
        "query": query_text,
        "ids": results.get("ids", [[]])[0],
        "documents": results.get("documents", [[]])[0],
        "distances": results.get("distances", [[]])[0],
    }


def health_check() -> dict[str, dict]:
    """
    Return a health summary for all collections.

    Returns:
        {collection_name: {"document_count": int, "status": "ok" | "empty"}}
    """
    result: dict[str, dict] = {}
    for name in COLLECTIONS:
        try:
            col = get_or_create_collection(name)
            count = col.count()
            result[name] = {
                "document_count": count,
                "status": "ok" if count > 0 else "empty",
            }
        except Exception as exc:
            logger.error("ChromaDB health check failed for '%s': %s", name, exc)
            result[name] = {"document_count": 0, "status": "error", "error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# Convenience query functions used by Agent 1 tools
# ---------------------------------------------------------------------------

def query_patient_records(
    query_text: str,
    patient_id: Optional[str] = None,
    n_results: int = 5,
) -> list[dict]:
    """
    Query the patient_records collection.
    If patient_id provided, filters by metadata (exact match).
    """
    col = get_or_create_collection("patient_records")
    if col.count() == 0:
        return []

    where = {"patient_id": patient_id} if patient_id else None
    results = col.query(
        query_texts=[query_text],
        n_results=min(n_results, col.count()),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return _format_results(results)


def query_claims_data(
    query_text: str,
    patient_id: Optional[str] = None,
    n_results: int = 5,
) -> list[dict]:
    """Query the claims_data collection."""
    col = get_or_create_collection("claims_data")
    if col.count() == 0:
        return []

    where = {"patient_id": patient_id} if patient_id else None
    results = col.query(
        query_texts=[query_text],
        n_results=min(n_results, col.count()),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return _format_results(results)


def query_medical_knowledge(
    query_text: str,
    icd_code: Optional[str] = None,
    n_results: int = 5,
) -> list[dict]:
    """Query the medical_knowledge collection. Optionally filter by icd_code."""
    col = get_or_create_collection("medical_knowledge")
    if col.count() == 0:
        return []

    where = {"icd_code": icd_code} if icd_code else None
    results = col.query(
        query_texts=[query_text],
        n_results=min(n_results, col.count()),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    return _format_results(results)


def query_underwriting_guidelines(query_text: str, n_results: int = 5) -> list[dict]:
    """Query the underwriting_guidelines collection."""
    col = get_or_create_collection("underwriting_guidelines")
    if col.count() == 0:
        return []

    results = col.query(
        query_texts=[query_text],
        n_results=min(n_results, col.count()),
        include=["documents", "metadatas", "distances"],
    )
    return _format_results(results)


def query_policy_documents(query_text: str, n_results: int = 5) -> list[dict]:
    """Query the policy_documents collection."""
    col = get_or_create_collection("policy_documents")
    if col.count() == 0:
        return []

    results = col.query(
        query_texts=[query_text],
        n_results=min(n_results, col.count()),
        include=["documents", "metadatas", "distances"],
    )
    return _format_results(results)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_results(raw: dict) -> list[dict]:
    """Flatten ChromaDB query result into a list of dicts."""
    docs = raw.get("documents", [[]])[0]
    metas = raw.get("metadatas", [[]])[0]
    distances = raw.get("distances", [[]])[0]
    ids = raw.get("ids", [[]])[0]

    return [
        {
            "id": ids[i] if i < len(ids) else None,
            "document": docs[i] if i < len(docs) else "",
            "metadata": metas[i] if i < len(metas) else {},
            "distance": distances[i] if i < len(distances) else 1.0,
            "relevance_score": round(1 - (distances[i] if i < len(distances) else 1.0), 4),
        }
        for i in range(len(docs))
    ]
