"""
Ingestion script for MedUnderwrite AI synthetic documents and knowledge bases.
Loads:
  1. Applicant documents (medical, claims, policy, underwriting) -> applicant_documents
  2. Regulatory reference guidelines -> regulatory_knowledge
  3. Underwriting guidelines & pricing rules -> underwriting_knowledge
  4. Medical knowledge concepts -> medical_knowledge
"""
import sys
from pathlib import Path

# Add backend directory to sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.rag.document_loader import document_loader
from app.rag.indexer import document_indexer
from app.store.vector_store import vector_store


def ingest_all():
    print("=" * 60)
    print("Ingesting MedUnderwrite AI synthetic dataset into ChromaDB")
    print("=" * 60)

    # 1. Ingest Applicant Documents (APP-TEST-001, APP-TEST-002, etc.)
    applicants_dir = settings.base_path / "data" / "synthetic" / "applicants"
    if applicants_dir.exists():
        print(f"\n1. Indexing applicant files from: {applicants_dir}")
        res = document_indexer.index_all_applicants(applicants_dir)
        print(f"   Processed applicants: {res.get('applicants_processed', 0)}")
        print(f"   Indexed documents   : {res.get('documents_indexed', 0)}")
        print(f"   Indexed chunks      : {res.get('chunks_indexed', 0)}")
    else:
        print(f"Applicants directory not found at: {applicants_dir}")

    # 2. Ingest Regulatory Knowledge
    reg_dir = settings.base_path / "data" / "synthetic" / "underwriting" / "guidelines"
    reg_file = reg_dir / "REG-DEMO-001_regulatory_reference.pdf"
    if reg_file.exists():
        print(f"\n2. Indexing regulatory reference from: {reg_file.name}")
        chunks = document_loader.load_file(reg_file)
        docs = [c["text"] for c in chunks if c.get("text")]
        ids = [f"reg_{i}" for i in range(len(docs))]
        metas = [
            {"source": "regulatory_reference", "file_name": reg_file.name, "jurisdiction": "India", "authority": "IRDAI"}
            for _ in docs
        ]
        if docs:
            vector_store.add_documents("regulatory_knowledge", documents=docs, ids=ids, metadatas=metas)
            print(f"   Indexed {len(docs)} regulatory chunks.")
    else:
        print(f"Regulatory file not found: {reg_file}")

    # 3. Ingest Underwriting Guidelines & Pricing Rules
    uw_guideline_file = reg_dir / "UW-DEMO-001_underwriting_guidelines.pdf"
    pricing_file = settings.base_path / "data" / "synthetic" / "underwriting" / "rules" / "PR-DEMO-001_pricing_rules.pdf"

    uw_docs, uw_ids, uw_metas = [], [], []
    if uw_guideline_file.exists():
        chunks = document_loader.load_file(uw_guideline_file)
        for i, c in enumerate(chunks):
            if c.get("text"):
                uw_docs.append(c["text"])
                uw_ids.append(f"uw_guide_{i}")
                uw_metas.append({"source": "underwriting_guidelines", "file_name": uw_guideline_file.name})

    if pricing_file.exists():
        chunks = document_loader.load_file(pricing_file)
        for i, c in enumerate(chunks):
            if c.get("text"):
                uw_docs.append(c["text"])
                uw_ids.append(f"uw_price_{i}")
                uw_metas.append({"source": "pricing_rules", "file_name": pricing_file.name})

    if uw_docs:
        print(f"\n3. Indexing underwriting guidelines & pricing rules")
        vector_store.add_documents("underwriting_knowledge", documents=uw_docs, ids=uw_ids, metadatas=uw_metas)
        print(f"   Indexed {len(uw_docs)} underwriting/pricing chunks.")

    # 4. Ingest Medical Knowledge
    med_file = settings.base_path / "data" / "synthetic" / "evaluation" / "medical_knowledge" / "medical_knowledge.txt"
    if med_file.exists():
        print(f"\n4. Indexing medical knowledge concepts from: {med_file.name}")
        chunks = document_loader.load_file(med_file)
        docs = [c["text"] for c in chunks if c.get("text")]
        ids = [f"med_{i}" for i in range(len(docs))]
        metas = [
            {"source": "medical_knowledge_reference", "file_name": med_file.name}
            for _ in docs
        ]
        if docs:
            vector_store.add_documents("medical_knowledge", documents=docs, ids=ids, metadatas=metas)
            print(f"   Indexed {len(docs)} medical knowledge chunks.")
    else:
        print(f"Medical knowledge file not found: {med_file}")

    print("\n" + "=" * 60)
    print("Vector Store Ingestion Complete!")
    print("Collections available:")
    for col in vector_store.list_collections():
        c = vector_store.client.get_collection(col)
        print(f"  - {col}: {c.count()} chunks")
    print("=" * 60)


if __name__ == "__main__":
    ingest_all()
