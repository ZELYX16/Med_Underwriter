"""
Table-aware reading and mismatch checks, against a real applicant bundle.

Uses docs/APP-009.zip (15 synthetic PDFs: proposal, policy schedule, five
claim records and eight medical reports). Skipped when the bundle or pypdf is
not available. No LLM, vector store or database is needed.
"""
from __future__ import annotations

import copy
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("pypdf")

from app.agents.fraud import MATERIAL_FLAG_CODES, assess_fraud
from app.rag import structured as st
from app.services.medical_groups import (
    declared_groups,
    diagnosis_group,
    icd_group,
    text_group,
)

ZIP_PATH = Path(__file__).resolve().parents[2] / "docs" / "APP-009.zip"

pytestmark = pytest.mark.skipif(
    not ZIP_PATH.exists(), reason="docs/APP-009.zip not present"
)


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    dest = tmp_path_factory.mktemp("app009")
    with zipfile.ZipFile(ZIP_PATH) as archive:
        for info in archive.infolist():
            target = (dest / info.filename).resolve()
            assert str(target).startswith(str(dest.resolve())), "unsafe zip path"
        archive.extractall(dest)
    root = next(dest.glob("APP-*"))
    paths = sorted(root.rglob("*.pdf"))
    facts = st.build_applicant_facts(paths)
    facts["available"] = True
    return root, facts


def _profile(facts):
    sub = facts["submission"]
    return {
        "name": sub["name"],
        "applicant_id": sub["applicant_id"],
        "medical_conditions": sub["conditions"],
        "smoker": None,
    }


def test_every_document_is_parsed(bundle):
    _, facts = bundle
    assert len(facts["documents"]) == 15
    assert facts["unparsed_files"] == []


def test_submission_tables_are_read_row_by_row(bundle):
    _, facts = bundle
    sub = facts["submission"]
    assert [c["year_diagnosed"] for c in sub["conditions"]] == [2024, 2023, 2025]
    assert sub["conditions"][0]["condition"].startswith("Lumbar disc herniation")
    # no table header text leaks into the declared data
    assert all("Year diagnosed" not in c["condition"] for c in sub["conditions"])
    assert [m["name"] for m in sub["medications"]] == [
        "Pantoprazole", "Pregabalin", "Tamsulosin", "Aceclofenac",
    ]
    assert sub["medications"][1]["indication"] == "Nerve pain (radiculopathy)"
    assert len(sub["hospitalizations"]) == 5
    assert sub["hospitalizations"][0]["start_date"] == "2023-05-09"
    assert sub["sum_insured"] == 1_000_000
    assert sub["claim_ids"] == [f"CLM-0090{i}" for i in range(1, 6)]
    statuses = {d["document"]: d["status"] for d in sub["supporting_documents"]}
    assert statuses["Endoscopy report, Oct 2025"] == "Not submitted"


def test_medical_documents_give_diagnoses_vitals_and_lifestyle(bundle):
    _, facts = bundle
    icds = {d["icd"] for d in facts["diagnoses"]}
    assert {"M51.16", "Z87.442", "K21.9", "N20.1", "N13.2"} <= icds
    assert facts["vitals"]["bmi"] == pytest.approx(29.4)
    assert facts["smoking"] == "non-smoker"
    assert any("kidney stones" in f["text"] for f in facts["family_history"])


def test_claim_records_match_the_policy_schedule(bundle):
    _, facts = bundle
    records = {c["claim_id"]: c for c in facts["claim_records"]}
    schedule = {c["claim_id"]: c for c in facts["policy"]["claims"]}
    assert set(records) == set(schedule) and len(records) == 5
    assert records["CLM-00901"]["approved"] == 105_900
    for claim_id, record in records.items():
        assert record["approved"] == schedule[claim_id]["approved"]
    assert facts["policy"]["specific_illness_months"] == 24
    assert "urinary-system calculi" in facts["policy"]["specific_illness_conditions"]


def test_condition_groups_match_wording_not_words():
    assert icd_group("N20.1") == icd_group("Z87.442") == "urinary_calculi"
    assert text_group("Recurrent urinary tract calculi (kidney stones)") == "urinary_calculi"
    assert diagnosis_group("Renal colic", "N23") == "urinary_calculi"
    # chronic kidney disease is a different, material condition
    assert diagnosis_group("Chronic kidney disease, stage 3", "N18.3") == "renal"
    assert diagnosis_group("Hypertension", "I10") == "hypertension"


def test_declared_kidney_stones_are_not_flagged_as_undeclared_renal_disease(bundle):
    _, facts = bundle
    result = assess_fraud(_profile(facts), {}, {"structured": facts})
    assert result["fraud_flags"] == []
    assert result["fraud_risk_score"] == 0
    # patterns are notes, not mismatches
    assert any(n["code"] == "claim_pattern" for n in result["fraud_notes"])


def test_questionnaire_details_decide_which_condition_was_declared(bundle):
    _, facts = bundle
    sub = facts["submission"]
    groups = declared_groups(sub["conditions"], sub["questionnaire"])
    assert "urinary_calculi" in groups
    assert "renal" not in groups  # stones were declared, not kidney disease


def test_real_mismatches_are_flagged(bundle):
    _, facts = bundle
    altered = copy.deepcopy(facts)
    altered["diagnoses"].append(
        {"diagnosis": "Chronic kidney disease, stage 3", "icd": "N18.3",
         "group": "renal", "document_id": "MR-00903"}
    )
    altered["smoking"] = "smoker"
    for doc in altered["documents"]:
        if doc["document_id"] == "MR-00904":
            doc["identity_problems"] = [
                {"field": "name", "found": "Rakesh Bhatt", "expected": "Nikhil Bhatt", "material": False},
                {"field": "date of birth", "found": "1985-01-27", "expected": "1984-01-27", "material": True},
            ]
    altered["claim_records"][2]["approved"] = 63_200.0

    result = assess_fraud(_profile(altered), {}, {"structured": altered})
    codes = {f["code"] for f in result["fraud_flags"]}
    assert {"undeclared_condition", "undeclared_smoker", "identity_mismatch",
            "claim_record_mismatch"} <= codes
    assert codes & MATERIAL_FLAG_CODES
    assert result["mandatory_reasons"], "CKD stage 3 and a mismatched document are mandatory"
    assert result["fraud_confirmed"] is False
    assert result["fraud_risk_level"] == "high"


def test_family_history_and_negations_are_not_non_disclosure_in_free_text():
    features = {
        "conditions": [], "medications": [], "claims": [], "claim_count": 0,
        "medical_evidence": [{
            "content": "Both parents had type 2 diabetes; sister had breast cancer at 55. "
                       "No renal angle tenderness. Renal function normal."
        }],
        "claims_evidence": [],
    }
    assert assess_fraud({"smoker": None}, {}, features)["fraud_flags"] == []

    features["medical_evidence"] = [{
        "content": "Type 2 diabetes mellitus treated with metformin since 2018."
    }]
    flags = assess_fraud({"smoker": None}, {}, features)["fraud_flags"]
    assert [f["code"] for f in flags] == ["undeclared_condition"]


def test_only_the_medical_examination_blocks_a_decision(bundle):
    _, facts = bundle
    sub = facts["submission"]
    profile = {"age": sub["age"], "medical_conditions": sub["conditions"],
               "existing_policy": {"policy_id": "POL-009"}, "claims": []}
    ok = st.document_requirements(facts, profile, {"sum_insured": sub["sum_insured"]})
    assert ok["blocking_missing"] == []
    outstanding = {o["document"] for o in ok["outstanding"]}
    assert "Endoscopy report, Oct 2025" in outstanding

    no_exam = copy.deepcopy(facts)
    no_exam["has_medical_examination"] = False
    blocked = st.document_requirements(no_exam, profile, {"sum_insured": sub["sum_insured"]})
    assert [m["document"] for m in blocked["blocking_missing"]] == [
        "Pre-policy medical examination report"
    ]


def test_chunks_carry_their_section_and_table_headers(bundle):
    root, _ = bundle
    doc = st.parse_pdf(root / "medical" / "MR-00901_medical_examination.pdf")
    chunks = st.section_chunks(doc)
    sections = {c["section"] for c in chunks}
    assert "5. Known Diagnoses" in sections
    diagnoses = next(c for c in chunks if c["section"] == "5. Known Diagnoses")
    assert diagnoses["text"].startswith("[Medical Examination Report MR-00901 | 5. Known Diagnoses]")
    assert "ICD-10-CM: Z87.442" in diagnoses["text"]