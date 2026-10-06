"""
MedUnderwrite AI — Data Ingestion Script

Loads three datasets into ChromaDB:
  1. MIMIC-IV subset      → patient_records collection
  2. CMS SynPUFs subset   → claims_data collection
  3. MedRAG knowledge     → medical_knowledge collection

Also seeds placeholder records in policy_documents and underwriting_guidelines
so Agent 1 tools always have something to query even without real data files.

Usage (from project root):
    python backend/scripts/load_data.py
"""
from __future__ import annotations

import csv
import json
import logging
import sys
import uuid
from pathlib import Path

# Ensure app package is importable when run directly
ROOT = Path(__file__).resolve().parents[2]          # backend/
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.store.chroma_setup import get_or_create_collection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

settings = get_settings()
DATA_DIR = Path(settings.chroma_path).parent / "datasets"   # ./data/datasets/


# ---------------------------------------------------------------------------
# 1. Load MIMIC-IV subset → patient_records
# ---------------------------------------------------------------------------

def load_patient_records(csv_path: Path) -> int:
    """
    Expected CSV columns:
        patient_id, age, gender, icd_codes (comma-sep), ehr_summary
    """
    collection = get_or_create_collection("patient_records")
    loaded = 0

    if not csv_path.exists():
        logger.warning("MIMIC-IV file not found at %s — skipping.", csv_path)
        return 0

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        ids, docs, metas = [], [], []

        for row in reader:
            doc_text = (
                f"Patient {row['patient_id']}: Age {row['age']}, Gender {row['gender']}. "
                f"ICD-10 codes: {row.get('icd_codes', '')}. "
                f"Summary: {row.get('ehr_summary', '')}"
            )
            ids.append(row["patient_id"])
            docs.append(doc_text)
            metas.append({
                "patient_id": row["patient_id"],
                "age": int(row.get("age", 0)),
                "gender": row.get("gender", "U"),
                "icd_codes": row.get("icd_codes", ""),
                "source": "mimic_iv",
            })
            loaded += 1

            # Batch upsert every 100 records
            if len(ids) >= 100:
                collection.upsert(ids=ids, documents=docs, metadatas=metas)
                logger.info("  patient_records: %d records upserted so far …", loaded)
                ids, docs, metas = [], [], []

        if ids:
            collection.upsert(ids=ids, documents=docs, metadatas=metas)

    logger.info("✅ patient_records: %d records loaded.", loaded)
    return loaded


# ---------------------------------------------------------------------------
# 2. Load CMS SynPUFs → claims_data
# ---------------------------------------------------------------------------

def load_claims_data(csv_path: Path) -> int:
    """
    Expected CSV columns:
        patient_id, age_group, conditions (comma-sep), total_claims, total_paid
    """
    collection = get_or_create_collection("claims_data")
    loaded = 0

    if not csv_path.exists():
        logger.warning("CMS SynPUFs file not found at %s — skipping.", csv_path)
        return 0

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        ids, docs, metas = [], [], []

        for row in reader:
            doc_text = (
                f"Claims for patient {row['patient_id']}: "
                f"Age group {row.get('age_group', 'unknown')}, "
                f"Conditions: {row.get('conditions', '')}. "
                f"Total claims: {row.get('total_claims', 0)}, "
                f"Total paid: EUR {row.get('total_paid', 0)}."
            )
            ids.append(f"claim_{row['patient_id']}")
            docs.append(doc_text)
            metas.append({
                "patient_id": row["patient_id"],
                "age_group": row.get("age_group", "unknown"),
                "conditions": row.get("conditions", ""),
                "total_claims": int(row.get("total_claims", 0)),
                "total_paid": float(row.get("total_paid", 0)),
                "source": "cms_synpufs",
            })
            loaded += 1

            if len(ids) >= 100:
                collection.upsert(ids=ids, documents=docs, metadatas=metas)
                logger.info("  claims_data: %d records upserted so far …", loaded)
                ids, docs, metas = [], [], []

        if ids:
            collection.upsert(ids=ids, documents=docs, metadatas=metas)

    logger.info("✅ claims_data: %d records loaded.", loaded)
    return loaded


# ---------------------------------------------------------------------------
# 3. Load MedRAG knowledge graph → medical_knowledge
# ---------------------------------------------------------------------------

def load_medical_knowledge(json_path: Path) -> int:
    """
    Expected JSON structure:
        [{icd_code, name, description, comorbidities, risk_factors, guidelines}]
    """
    collection = get_or_create_collection("medical_knowledge")
    loaded = 0

    if not json_path.exists():
        logger.warning("MedRAG file not found at %s — seeding defaults.", json_path)
        _seed_default_medical_knowledge(collection)
        return 0

    with open(json_path, encoding="utf-8") as fh:
        records: list[dict] = json.load(fh)

    ids, docs, metas = [], [], []
    for entry in records:
        icd = entry.get("icd_code", "UNKNOWN")
        doc_text = (
            f"ICD-10 {icd}: {entry.get('name', '')}. "
            f"{entry.get('description', '')} "
            f"Comorbidities: {', '.join(entry.get('comorbidities', []))}. "
            f"Risk factors: {', '.join(entry.get('risk_factors', []))}. "
            f"Guidelines: {entry.get('guidelines', '')}"
        )
        ids.append(f"med_{icd}_{uuid.uuid4().hex[:6]}")
        docs.append(doc_text)
        metas.append({
            "icd_code": icd,
            "name": entry.get("name", ""),
            "category": entry.get("category", "general"),
            "tier": entry.get("tier", "standard"),
            "source": "medrag",
        })
        loaded += 1

    if ids:
        collection.upsert(ids=ids, documents=docs, metadatas=metas)

    logger.info("✅ medical_knowledge: %d entries loaded.", loaded)
    return loaded


def _seed_default_medical_knowledge(collection) -> None:
    """Seed a minimal set of ICD-10 entries so queries always return results."""
    defaults = [
        {
            "icd_code": "E11.9", "name": "Type 2 Diabetes Mellitus without complications",
            "description": "Chronic metabolic disorder characterised by hyperglycaemia.",
            "comorbidities": ["I10", "I25.9", "E78"],
            "risk_factors": ["obesity", "sedentary_lifestyle", "family_history"],
            "guidelines": "HbA1c monitoring every 3 months. Metformin first-line.",
            "category": "endocrine", "tier": "standard",
        },
        {
            "icd_code": "I10", "name": "Essential Hypertension",
            "description": "Elevated arterial blood pressure with no identifiable cause.",
            "comorbidities": ["E11.9", "I25.9", "N18"],
            "risk_factors": ["high_sodium", "obesity", "stress"],
            "guidelines": "Target BP < 130/80 mmHg. Lisinopril or amlodipine first-line.",
            "category": "cardiovascular", "tier": "standard",
        },
        {
            "icd_code": "I25.9", "name": "Chronic Ischaemic Heart Disease, unspecified",
            "description": "Narrowing of coronary arteries reducing blood flow to the heart.",
            "comorbidities": ["E11.9", "I10", "I50"],
            "risk_factors": ["smoking", "hyperlipidaemia", "diabetes", "hypertension"],
            "guidelines": "Annual cardiac review. Statin therapy. Aspirin if indicated.",
            "category": "cardiovascular", "tier": "high_risk",
        },
        {
            "icd_code": "J45.9", "name": "Asthma, unspecified",
            "description": "Chronic inflammatory airway disease causing reversible obstruction.",
            "comorbidities": ["J30", "J44"],
            "risk_factors": ["allergens", "smoking", "respiratory_infections"],
            "guidelines": "Step-up therapy per GINA guidelines. Peak flow monitoring.",
            "category": "respiratory", "tier": "standard",
        },
        {
            "icd_code": "M79.3", "name": "Panniculitis",
            "description": "Inflammation of the subcutaneous fat layer.",
            "comorbidities": [],
            "risk_factors": ["obesity", "trauma"],
            "guidelines": "Anti-inflammatory treatment as needed.",
            "category": "musculoskeletal", "tier": "low_risk",
        },
    ]

    ids, docs, metas = [], [], []
    for entry in defaults:
        icd = entry["icd_code"]
        doc_text = (
            f"ICD-10 {icd}: {entry['name']}. {entry['description']} "
            f"Comorbidities: {', '.join(entry['comorbidities'])}. "
            f"Risk factors: {', '.join(entry['risk_factors'])}. "
            f"Guidelines: {entry['guidelines']}"
        )
        ids.append(f"med_{icd}_default")
        docs.append(doc_text)
        metas.append({
            "icd_code": icd,
            "name": entry["name"],
            "category": entry["category"],
            "tier": entry["tier"],
            "source": "medrag_default",
        })

    collection.upsert(ids=ids, documents=docs, metadatas=metas)
    logger.info("  medical_knowledge: seeded %d default ICD-10 entries.", len(ids))


# ---------------------------------------------------------------------------
# 4. Seed policy_documents & underwriting_guidelines
# ---------------------------------------------------------------------------

def seed_policy_documents() -> int:
    """Seed basic Allianz-style policy document stubs."""
    collection = get_or_create_collection("policy_documents")

    policies = [
        {
            "id": "pol_basic_health",
            "text": (
                "Basic Health Insurance Policy (BHP-001). Coverage: inpatient, outpatient, "
                "prescription drugs. Limit: EUR 100,000/year. Exclusions: cosmetic procedures, "
                "experimental treatments. Waiting period: 3 months for pre-existing conditions."
            ),
            "meta": {"policy_type": "basic_health", "coverage_limit": 100000},
        },
        {
            "id": "pol_comprehensive",
            "text": (
                "Comprehensive Health Policy (CHP-001). Coverage: all BHP-001 plus dental, "
                "vision, cardiac rehabilitation, specialist referrals. Limit: EUR 250,000/year. "
                "No waiting period for emergency cardiac care."
            ),
            "meta": {"policy_type": "comprehensive", "coverage_limit": 250000},
        },
        {
            "id": "pol_cardiac_rehab_gap",
            "text": (
                "Coverage Gap Notice: Cardiac rehabilitation not included in BHP-001. "
                "Patients with ICD-10 I25.x or I21.x should be offered cardiac rehab rider "
                "at EUR 45/month additional premium."
            ),
            "meta": {"policy_type": "gap_notice", "condition": "cardiac_rehab"},
        },
    ]

    collection.upsert(
        ids=[p["id"] for p in policies],
        documents=[p["text"] for p in policies],
        metadatas=[p["meta"] for p in policies],
    )
    logger.info("✅ policy_documents: %d records seeded.", len(policies))
    return len(policies)


def seed_underwriting_guidelines() -> int:
    """Seed actuarial benchmarks and UW decision rules."""
    collection = get_or_create_collection("underwriting_guidelines")

    guidelines = [
        {
            "id": "uw_loading_diabetes",
            "text": (
                "Actuarial Guideline UW-DM-001: Type 2 Diabetes (E11.9). "
                "Base loading: 15% of base premium. "
                "If HbA1c > 9%: +5% additional. "
                "If on insulin: +10% additional. "
                "Combined cap: +30%."
            ),
            "meta": {"rule_type": "loading", "icd_code": "E11.9", "base_loading_pct": 15},
        },
        {
            "id": "uw_loading_hypertension",
            "text": (
                "Actuarial Guideline UW-HTN-001: Essential Hypertension (I10). "
                "Controlled (BP < 140/90): 10% loading. "
                "Uncontrolled: 20% loading. "
                "On 3+ antihypertensives: +5%."
            ),
            "meta": {"rule_type": "loading", "icd_code": "I10", "base_loading_pct": 10},
        },
        {
            "id": "uw_loading_cardiac",
            "text": (
                "Actuarial Guideline UW-CAD-001: Ischaemic Heart Disease (I25.9). "
                "Post-cardiac event (> 2yr ago, stable): 20% loading. "
                "Recent event (< 2yr): 40% loading or decline. "
                "CABG/stent: +10% additional. "
                "Triggers COMPLEX path in routing."
            ),
            "meta": {"rule_type": "loading", "icd_code": "I25.9", "base_loading_pct": 20},
        },
        {
            "id": "uw_routing_rules",
            "text": (
                "Routing Rules (complexity_router). "
                "0–1 ICD-10 conditions, no red flags → STANDARD path (Plan-and-Execute). "
                "2+ conditions OR any high-risk ICD code → COMPLEX path (Tree-of-Thought). "
                "3+ conditions + cardiac/oncology → HITL fast-track."
            ),
            "meta": {"rule_type": "routing"},
        },
        {
            "id": "uw_base_rates",
            "text": (
                "Base Premium Rate Table. Age 18–30: EUR 185/month. "
                "Age 31–45: EUR 240/month. Age 46–55: EUR 310/month. "
                "Age 56–65: EUR 395/month. Age 66+: EUR 520/month. "
                "Gender: no differentiation (community rating, EU regulation)."
            ),
            "meta": {"rule_type": "base_rate"},
        },
    ]

    collection.upsert(
        ids=[g["id"] for g in guidelines],
        documents=[g["text"] for g in guidelines],
        metadatas=[g["meta"] for g in guidelines],
    )
    logger.info("✅ underwriting_guidelines: %d records seeded.", len(guidelines))
    return len(guidelines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("=" * 60)
    logger.info("MedUnderwrite AI — Data Ingestion")
    logger.info("=" * 60)

    totals: dict[str, int] = {}

    # Patient records
    mimic_path = DATA_DIR / "mimic_iv_subset.csv"
    totals["patient_records"] = load_patient_records(mimic_path)

    # Claims data
    cms_path = DATA_DIR / "cms_synpufs_subset.csv"
    totals["claims_data"] = load_claims_data(cms_path)

    # Medical knowledge (seeds defaults if JSON not found)
    medrag_path = DATA_DIR / "medrag_knowledge.json"
    totals["medical_knowledge"] = load_medical_knowledge(medrag_path)

    # Seeded collections
    totals["policy_documents"] = seed_policy_documents()
    totals["underwriting_guidelines"] = seed_underwriting_guidelines()

    # Final health check
    logger.info("\n--- Final Collection Counts ---")
    for name, count in totals.items():
        logger.info("  %-30s → %d documents", name, count)
    logger.info("=" * 60)
    logger.info("✅ Data ingestion complete. ChromaDB is ready.")


if __name__ == "__main__":
    main()
