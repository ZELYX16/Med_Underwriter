"""
Routing, evidence states, severity, role-aware identity and lab extraction.

Pure logic: no LLM, vector store or database. Where a real applicant bundle
(docs/APP-001.zip, docs/APP-002.zip) is present it is also checked.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from app.agents.fraud import assess_fraud
from app.rag import structured as st
from app.services.evidence_state import completeness, evidence_states, verification_items
from app.services.severity import assess_conditions, assess_group

DOCS = Path(__file__).resolve().parents[2] / "docs"


# ---------------------------------------------------------------------------
# Serious undeclared conditions escalate; routine controlled ones do not
# ---------------------------------------------------------------------------

def test_undeclared_nstemi_and_stent_force_review_even_with_a_low_score():
    features = {
        "conditions": [], "medications": [], "claims": [], "claim_count": 0, "sum_insured": 500_000,
        "age": 38,
        "medical_evidence": [{
            "content": "History of NSTEMI in 2022 treated with coronary stent placement. "
                       "Taking aspirin and atorvastatin."
        }],
        "claims_evidence": [],
    }
    result = assess_fraud({"smoker": None}, {}, features)
    serious = [f for f in result["fraud_flags"] if f["code"] == "undeclared_condition"]
    assert serious and all(f["mandatory"] and f["tier"] == "serious" for f in serious)
    assert result["mandatory_reasons"], "serious undeclared condition must be a mandatory reason"
    assert result["fraud_confirmed"] is False


def _structured_facts(diagnoses, **extra):
    base = {
        "available": True, "documents": [], "diagnoses": diagnoses, "vitals": {},
        "labs": [], "medications": [], "narrative": "", "negatives": [],
        "submission": {"questionnaire": [], "age": 40}, "claim_records": [], "policy": None,
        "age_issues": [], "smoking": None,
    }
    base.update(extra)
    return base


def test_undeclared_controlled_hypertension_is_a_note_not_an_escalation():
    facts = _structured_facts(
        [{"diagnosis": "Essential hypertension", "icd": "I10", "group": "hypertension", "document_id": "MR-1"}],
        vitals={"blood_pressure": "124/80 mmHg", "bmi": 27.5},
        medications=[{"name": "Amlodipine", "details": "5 mg once daily"}],
    )
    result = assess_fraud({"medical_conditions": []}, {}, {"structured": facts, "age": 40})
    flag = next(f for f in result["fraud_flags"] if f["code"] == "undeclared_condition")
    assert flag["tier"] == "routine" and flag["control"] == "controlled"
    assert not flag["mandatory"] and not flag["requires_review"]
    assert result["mandatory_reasons"] == [] and result["verification_reasons"] == []


def test_overweight_bmi_alone_never_produces_a_finding():
    facts = _structured_facts([], vitals={"bmi": 28.4, "blood_pressure": "118/76 mmHg"})
    result = assess_fraud({"medical_conditions": []}, {}, {"structured": facts, "age": 35})
    assert result["fraud_flags"] == [] and result["mandatory_reasons"] == []


def test_uncontrolled_hypertension_or_complications_are_serious():
    controlled = assess_group("hypertension", text="hypertension", vitals={"blood_pressure": "126/82 mmHg"})
    uncontrolled = assess_group("hypertension", text="hypertension", vitals={"blood_pressure": "172/104 mmHg"})
    complicated = assess_group(
        "hypertension", text="hypertension with left ventricular hypertrophy",
        vitals={"blood_pressure": "130/80 mmHg"},
    )
    unknown = assess_group("hypertension", text="hypertension")
    assert (controlled["tier"], controlled["control"]) == ("routine", "controlled")
    assert uncontrolled["tier"] == "serious"
    assert complicated["tier"] == "serious" and complicated["complications"]
    assert unknown["tier"] == "indeterminate" and unknown["missing"]


def test_family_history_of_heart_attack_is_not_the_applicants_event():
    cardiac = assess_group("cardiac", text="Father had a heart attack at 60. No chest pain.")
    assert cardiac["tier"] != "serious"


# ---------------------------------------------------------------------------
# Diabetes with reassuring labs (APP-002 scenario)
# ---------------------------------------------------------------------------

LABS = [
    {"name": "Fasting glucose", "value": 94.0, "unit": "mg/dL", "document_id": "MR-00202"},
    {"name": "Serum creatinine", "value": 0.9, "unit": "mg/dL", "document_id": "MR-00202"},
    {"name": "eGFR", "value": 98.0, "unit": "mL/min/1.73m2", "document_id": "MR-00202"},
    {"name": "Urine albumin-creatinine ratio", "value": 12.0, "unit": "mg/g", "document_id": "MR-00202"},
]


def test_reassuring_labs_do_not_mean_diabetes_is_absent_or_controlled():
    groups = {"diabetes": {"text": "Type 2 diabetes mellitus on metformin", "icd": [], "declared": True,
                           "sources": ["MR-00202"], "onset_known": False}}
    [a] = assess_conditions(
        groups=groups, vitals={}, labs=LABS, medications=[{"name": "Metformin"}],
        age=48, sum_insured=1_000_000,
    )
    assert a["tier"] == "indeterminate" and a["control"] == "unknown"
    assert set(a["missing"]) >= {"HbA1c", "diabetes duration", "complication history"}
    assert len(a["reassuring"]) == 4 and not a["complications"]
    assert a["material_missing"], "age 48 / 1,000,000 cover makes the gaps material"


def test_missing_diabetes_details_are_not_material_for_a_small_young_case():
    groups = {"diabetes": {"text": "Type 2 diabetes", "icd": [], "declared": True, "sources": [], "onset_known": True}}
    [a] = assess_conditions(groups=groups, vitals={}, labs=LABS, medications=[], age=31, sum_insured=300_000)
    assert a["missing"] and a["material_missing"] == []


def test_hba1c_decides_diabetes_control():
    base = dict(text="Type 2 diabetes since 2015. No retinopathy, nephropathy or neuropathy.", onset_known=True)
    good = assess_group("diabetes", labs=[{"name": "HbA1c", "value": 6.8}], **base)
    poor = assess_group("diabetes", labs=[{"name": "HbA1c", "value": 10.2}], **base)
    assert (good["tier"], good["control"]) == ("routine", "controlled")
    assert (poor["tier"], poor["control"]) == ("serious", "uncontrolled")


def _layout_table(header, rows, widths):
    def line(cells):
        return " " + "".join(str(c).ljust(w) for c, w in zip(cells, widths)).rstrip()
    return [line(header)] + [line(r) for r in rows]


def test_laboratory_table_is_read_with_units_ranges_and_flags():
    lines = _layout_table(
        ["Test", "Result", "Unit", "Reference range", "Flag"],
        [
            ["Fasting glucose", "94", "mg/dL", "70-99", "Normal"],
            ["Serum creatinine", "0.9", "mg/dL", "0.6-1.2", "Normal"],
            ["eGFR", "98", "mL/min/1.73m2", ">= 60", ""],
            ["Urine albumin-creatinine ratio", "12", "mg/g", "< 30", ""],
            ["HbA1c", "7.9", "%", "4.0-5.6", ""],
        ],
        [34, 10, 18, 20, 8],
    )
    doc = {"doc_id": "MR-00202", "sections": [{"number": 3, "title": "Laboratory", "blocks": st._blocks(lines)}]}
    labs = {l["name"]: l for l in st._lab_rows(doc, "MR-00202", "2026-08-01")}
    assert labs["Fasting glucose"]["value"] == 94 and labs["Fasting glucose"]["flag"] == "normal"
    assert labs["eGFR"]["reference"] == ">= 60" and labs["eGFR"]["flag"] == "normal"
    assert labs["Urine albumin-creatinine ratio"]["flag"] == "normal"
    assert labs["HbA1c"]["flag"] == "high"
    assert labs["eGFR"]["document_id"] == "MR-00202"


# ---------------------------------------------------------------------------
# Evidence states
# ---------------------------------------------------------------------------

def test_missing_claims_and_hospital_evidence_are_unknown_not_zero():
    states = evidence_states(profile={"claims": [], "hospitalizations": []}, structured={}, evidence={})
    assert states["claims"]["state"] == "unknown"
    assert states["hospitalizations"]["state"] == "unknown"
    assert states["medical"]["state"] == "unknown"
    assert completeness(states) < 1.0


def test_only_an_explicit_statement_makes_evidence_negative():
    structured = {"submission": {"questionnaire": [{"question": "Digestive disorder", "answer": "Yes", "details": "GERD"}]}}
    states = evidence_states(
        profile={"claims": [], "hospitalizations": [], "existing_policy": {}},
        structured=structured,
        evidence={"policy_evidence": [{"content": "Declared claims: None."}]},
    )
    assert states["claims"]["state"] == "negative"
    assert states["hospitalizations"]["state"] == "negative"  # questionnaire lists no admission
    assert states["policy"]["state"] == "positive"


def test_a_declared_policy_that_was_not_retrieved_means_coverage_not_assessed():
    states = evidence_states(
        profile={"existing_policy": {"policy_id": "POL-9"}}, structured={}, evidence={}
    )
    assert states["policy"]["state"] == "unknown"
    items = verification_items(
        states, conditions_declared=True, existing_policy_declared=True, sum_insured=2_000_000, age=50
    )
    material = {i["domain"] for i in items if i["material"]}
    assert {"claims", "policy", "medical"} <= material


def test_unknowns_are_not_material_for_a_small_simple_case():
    states = evidence_states(profile={}, structured={}, evidence={})
    items = verification_items(
        states, conditions_declared=False, existing_policy_declared=False, sum_insured=300_000, age=28
    )
    assert not any(i["material"] for i in items)


# ---------------------------------------------------------------------------
# Role-aware policy identity (APP-001: employer policyholder, member applicant)
# ---------------------------------------------------------------------------

def _policy_doc(policy_type, holder, insured):
    header = {
        "Document ID": "POL-001", "Applicant ID": "APP-001", "Policy holder": holder,
        "Policy type": policy_type, "Date of birth": "12-May-1992",
    }
    if insured is not None:
        header["Insured member"] = insured
    return {"doc_id": "POL-001", "doc_type": "policy", "title": "Policy", "header": header, "sections": []}


REFERENCE = {"name": "Ananya Krishnan", "dob": "1992-05-12", "applicant_id": "APP-001"}


def _entry(facts):
    return {
        "applicant_name": facts["match_name"] or None, "dob": facts["dob"], "applicant_id": facts["applicant_id"],
    }


def test_group_policy_is_matched_on_the_insured_member_not_the_employer():
    facts = st.policy_facts(_policy_doc("Group - employer", "Brightpath Software Solutions Pvt. Ltd.", "Ananya Krishnan"))
    assert facts["is_group"] and facts["match_name"] == "Ananya Krishnan"
    assert "not the policyholder" in facts["role_note"]
    assert st.identity_problems(_entry(facts), REFERENCE) == []


def test_individual_policy_uses_the_insured_member_then_the_holder():
    insured = st.policy_facts(_policy_doc("Individual", "Policy Holder Name", "Ananya Krishnan"))
    holder_only = st.policy_facts(_policy_doc("Individual", "Ananya Krishnan", None))
    assert insured["match_name"] == "Ananya Krishnan"
    assert holder_only["match_name"] == "Ananya Krishnan"
    assert st.identity_problems(_entry(holder_only), REFERENCE) == []


def test_group_policy_without_a_named_member_is_skipped_safely():
    facts = st.policy_facts(_policy_doc("Group - employer", "Brightpath Software Solutions Pvt. Ltd.", None))
    assert facts["match_name"] == ""
    assert st.identity_problems(_entry(facts), REFERENCE) == []  # employer is never compared


def test_a_conflicting_insured_member_is_a_verify_item_not_fraud():
    facts = st.policy_facts(_policy_doc("Group - employer", "Brightpath Software Solutions Pvt. Ltd.", "Someone Else"))
    problems = st.identity_problems(_entry(facts), REFERENCE)
    assert [p["field"] for p in problems] == ["name"] and not problems[0]["material"]


def test_age_is_computed_from_the_date_of_birth():
    assert st.age_on("1978-07-22", "2026-08-01") == 48
    assert st.age_on("1978-07-22", "2026-07-21") == 47
    assert st.age_on("bad", "2026-01-01") is None


def test_a_document_for_someone_else_is_flagged_and_its_facts_are_not_used():
    facts = _structured_facts(
        [],
        documents=[{
            "document_id": "MR-00202", "doc_type": "medical", "title": "Lab report",
            "identity_problems": [{"field": "date of birth", "found": "1978-07-22", "expected": "1976-03-01", "material": True}],
        }],
    )
    result = assess_fraud({"name": "Suresh Nair"}, {}, {"structured": facts, "age": 50})
    flag = next(f for f in result["fraud_flags"] if f["code"] == "identity_mismatch")
    assert flag["mandatory"] and "not" in flag["detail"]
    assert result["mandatory_reasons"]


# ---------------------------------------------------------------------------
# Mandatory review is sticky: Agent 3 / finalization cannot override it
# ---------------------------------------------------------------------------

def test_mandatory_reasons_survive_a_clean_reflection_and_finalization():
    pytest.importorskip("langgraph")
    from app.orchestrator.graph import _business_review_reasons, finalize_node

    state = {
        "mandatory_review_reasons": ["Mandatory review: Serious condition not declared: heart disease"],
        "agent2_recommendation": "standard_acceptance",
        "agent2_confidence": 0.95,
        "overall_risk_score": 8.0,
        "medical_risk_score": 5.0,
        "reflection_verdict": "pass",
        "reflection_round": 1,
        "reflection_consensus": True,
    }
    assert _business_review_reasons(state)
    out = finalize_node(state)
    assert out["final_status"] == "awaiting_human_review"
    assert out["final_recommendation"] == "human_review"


# ---------------------------------------------------------------------------
# Real bundles, when provided
# ---------------------------------------------------------------------------

def _bundle(name, tmp_path):
    path = DOCS / f"{name}.zip"
    if not path.exists():
        pytest.skip(f"docs/{name}.zip not present")
    pytest.importorskip("pypdf")
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            assert str((tmp_path / info.filename).resolve()).startswith(str(tmp_path.resolve()))
        archive.extractall(tmp_path)
    root = next(tmp_path.glob("APP-*"))
    facts = st.build_applicant_facts(sorted(root.rglob("*.pdf")))
    facts["available"] = True
    return facts


def _profile(facts):
    sub = facts["submission"] or {}
    return {"name": sub.get("name"), "applicant_id": sub.get("applicant_id"),
            "medical_conditions": sub.get("conditions", []), "age": sub.get("age")}


def test_app001_employer_policy_is_not_flagged(tmp_path):
    facts = _bundle("APP-001", tmp_path)
    result = assess_fraud(_profile(facts), {}, {"structured": facts, "age": _profile(facts)["age"]})
    assert not [f for f in result["fraud_flags"] if f["code"] == "identity_mismatch"]
    policy_docs = [d for d in facts["documents"] if d["doc_type"] == "policy"]
    assert policy_docs and all(d["identity_verified"] for d in policy_docs)


def test_app002_documents_are_tied_to_the_right_person(tmp_path):
    facts = _bundle("APP-002", tmp_path)
    excluded = set(facts["excluded_documents"])
    # a document whose identity does not match is listed but contributes
    # no diagnoses or labs
    lab_sources = {l["document_id"] for l in facts["labs"]}
    assert not lab_sources & excluded
    assert not {d["document_id"] for d in facts["diagnoses"]} & excluded