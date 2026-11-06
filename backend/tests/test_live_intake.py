"""
Live intake building blocks: form catalogue, requirements, sessions, upload
triage, compliance catalogue, graded outcomes and the cost guard.
Pure logic; no LLM, vector store or API server is needed.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.services import compliance, cost_guard, intake, outcome, scenarios
from app.services.evidence_state import evidence_states
from app.services.sessions import SessionStore
from app.services.triage import triage

FORM = {"name": "Test Person", "dob": "1990-01-01", "sex": "Female", "product": "MedShield Comprehensive",
        "sum_insured": 500000, "smoker": "no", "hospital_stay": "no", "had_claims": "no",
        "has_other_insurance": "no", "consent": True, "conditions": []}


# --- catalogue and typed conditions -------------------------------------------------------------------

def test_everyday_words_map_to_conditions_without_an_llm():
    assert intake.lookup_condition("my sugar is high")["key"] == "diabetes"
    assert intake.lookup_condition("BP")["key"] == "bp"
    assert intake.lookup_condition("I had a stent")["key"] == "heart"
    assert intake.lookup_condition("kidney stone")["key"] == "kidney"
    assert intake.lookup_condition("zzyzx")["matched"] is False


def test_followups_use_plain_words():
    technical = ("hba1c", "ejection", "icd", "eGFR", "ischaemic")
    for c in intake.CONDITIONS:
        asks = " ".join(f["ask"] for f in c["followups"])
        assert not any(t.lower() in c["label"].lower() for t in technical)
        assert asks, c["key"]


# --- what must be attached ---------------------------------------------------------------------------------

def test_a_young_healthy_small_application_needs_no_documents():
    assert intake.required_documents(FORM) == []


def test_age_cover_or_a_condition_requires_a_medical_checkup():
    older = {**FORM, "dob": f"{date.today().year - 52}-01-01"}
    assert [n["id"] for n in intake.required_documents(older) if n["blocking"]] == ["medical_exam"]
    big = {**FORM, "sum_insured": 1_500_000}
    assert any(n["blocking"] for n in intake.required_documents(big))
    ill = {**FORM, "conditions": [{"key": "diabetes", "answers": {}}]}
    ids = [n["id"] for n in intake.required_documents(ill)]
    assert "medical_exam" in ids and "diabetes_0" in ids


def test_open_items_block_until_answered_and_later_items_do_not_block():
    empty = intake.open_items({}, [])
    assert {"name", "dob", "consent"} <= {i["id"] for i in empty if i["blocking"]}
    assert not [i for i in intake.open_items(FORM, []) if i["blocking"]]

    ill = {**FORM, "conditions": [{"key": "bp", "answers": {}}]}
    assert any(i["id"] == "medical_exam" and i["blocking"] for i in intake.open_items(ill, []))
    later = intake.open_items({**ill, "docs_later": ["medical_exam", "bp_0"]}, [])
    assert not [i for i in later if i["blocking"]]
    done = intake.open_items(ill, [{"detected_type": "medical_exam", "status": "indexed", "requirement": None}])
    assert not any(i["id"] == "medical_exam" for i in done)
    rejected = intake.open_items(ill, [{"detected_type": "medical_exam", "status": "rejected", "requirement": "medical_exam"}])
    assert any(i["id"] == "medical_exam" for i in rejected)


def test_form_becomes_the_profile_the_pipeline_expects():
    form = {**FORM, "height_cm": 170, "weight_kg": 80, "hospital_stay": "yes", "hospital_details": "Stent 2021",
            "conditions": [{"key": "heart", "answers": {"since": "2021", "medicines": "Aspirin; Atorvastatin",
                                                        "event": "Stent in 2021"}}]}
    profile, submission = intake.to_profile_submission("APP-LV-1", form)
    assert profile["source"] == "live_session" and profile["bmi"] == 27.7
    assert profile["medical_conditions"][0]["condition"] == "Heart disease"
    assert profile["medical_conditions"][0]["year_diagnosed"] == 2021
    assert [m["name"] for m in profile["medications"]] == ["Aspirin", "Atorvastatin"]
    assert profile["hospitalizations"] and not profile["declarations"]["no_hospital_admission"]
    assert submission["sum_insured"] == 500000 and submission["consent"] is True


def test_every_sample_applicant_is_complete_apart_from_documents_to_attach():
    for item in scenarios.listing():
        scenario = scenarios.get(item["id"])
        blocking = [i for i in intake.open_items(scenario["form"], []) if i["blocking"]]
        if scenario.get("bundle"):
            assert {i["id"] for i in blocking} <= {"medical_exam"}
        else:
            assert not blocking, (item["id"], blocking)


# --- explicit answers are stated negatives -----------------------------------------------------------------------

def test_a_yes_no_answer_is_a_stated_negative_but_silence_is_unknown():
    profile, _ = intake.to_profile_submission("APP-LV-2", FORM)
    states = evidence_states(profile=profile, structured={}, evidence={})
    assert states["claims"]["state"] == "negative" and states["hospitalizations"]["state"] == "negative"
    silent = evidence_states(profile={"claims": [], "hospitalizations": []}, structured={}, evidence={})
    assert silent["claims"]["state"] == "unknown"


# --- sessions ------------------------------------------------------------------------------------------------------------

def test_a_session_survives_close_and_resume(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    session = store.create("APP-LV-9", "UW-LV-9")
    token = session["token"]
    store.update(token, form={"name": "A"})
    store.mutate_documents(token, lambda docs: docs + [{"id": "d1", "status": "indexing"}])
    store.mutate_documents(token, lambda docs: [{**d, "status": "indexed"} for d in docs])
    reopened = SessionStore(tmp_path / "s.db").get(token)
    assert reopened["form"] == {"name": "A"} and reopened["documents"][0]["status"] == "indexed"
    assert store.get("not-a-token") is None


def test_expired_sessions_cannot_be_resumed(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    token = store.create("A", "B")["token"]
    with store._conn() as conn:
        conn.execute("UPDATE application_sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    assert store.get(token) is None and store.purge_expired() == 1


# --- upload triage ---------------------------------------------------------------------------------------------------------

def _file(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_triage_accepts_the_applicants_own_document(tmp_path):
    path = _file(tmp_path, "MR-1_medical_examination.txt",
                 "MEDICAL EXAMINATION REPORT\nApplicant name: Test Person\nDate of birth 01-Jan-1990")
    result = triage(path, path.name, "medical_exam", FORM)
    assert result["status"] == "accepted" and result["folder"] == "medical"
    assert result["timing_sec"] < 1.0


def test_triage_rejects_someone_elses_document_before_any_indexing(tmp_path):
    path = _file(tmp_path, "report.txt", "Medical examination report\nApplicant name: Someone Else\n")
    result = triage(path, path.name, "medical_exam", FORM)
    assert result["status"] == "rejected" and "not 'Test Person'" in result["issues"][0]
    wrong_dob = _file(tmp_path, "r2.txt", "Medical examination report\nDate of birth: 05-May-1970\n")
    assert triage(wrong_dob, wrong_dob.name, None, FORM)["status"] == "rejected"


def test_triage_warns_about_the_wrong_kind_of_document(tmp_path):
    path = _file(tmp_path, "CLM-1_claim.txt", "Claim record\nClaim ID CLM-1")
    result = triage(path, path.name, "medical_exam", FORM)
    assert result["status"] == "warning" and result["detected_type"] == "claim"


def test_triage_does_not_compare_a_group_policy_holder_with_the_applicant(tmp_path):
    path = _file(tmp_path, "POL-1.txt",
                 "Health insurance policy schedule\nPolicy holder: Brightpath Software Solutions\n"
                 "Insured member: Test Person\nPolicy type: Group - employer")
    assert triage(path, path.name, "policy", FORM)["status"] == "accepted"


def test_triage_rejects_unreadable_types_and_detects_duplicates_by_hash(tmp_path):
    exe = _file(tmp_path, "x.exe", "MZ")
    assert triage(exe, exe.name, None, FORM)["status"] == "rejected"
    a = _file(tmp_path, "a.txt", "same text")
    b = _file(tmp_path, "b.txt", "same text")
    assert triage(a, a.name, None, FORM)["sha256"] == triage(b, b.name, None, FORM)["sha256"]


# --- compliance ----------------------------------------------------------------------------------------------------------------

def _ctx(**over):
    base = {"profile": {}, "submission": {"channel": "live_session", "consent": True}, "risk": {"risk_factors": ["Age 50 or above"],
            "evidence_states": {"medical": {"state": "positive"}, "policy": {"state": "positive"}},
            "verification_items": [], "coverage_notes": []}, "flags": [], "policy": None,
            "has_documents": True, "recommendation": "standard_acceptance", "mandatory": False, "provider": "ollama"}
    base.update(over)
    return base


def test_compliance_report_passes_a_clean_case_and_cites_a_source_for_every_rule():
    report = compliance.evaluate(_ctx())
    assert {r["id"] for r in report["rules"]} >= {"C01", "C02", "C03", "C04", "C06", "C09", "C10"}
    assert all(r["source"] and r["detail"] for r in report["rules"])
    assert report["summary"].get("fail", 0) == 0


def test_compliance_flags_missing_consent_serious_nondisclosure_and_protected_attributes():
    report = compliance.evaluate(_ctx(
        submission={"channel": "live_session", "consent": False},
        flags=[{"code": "undeclared_condition", "mandatory": True, "detail": "x"}],
        risk={"risk_factors": ["Gender is a risk factor"], "evidence_states": {}, "verification_items": []},
    ))
    status = {r["id"]: r["status"] for r in report["rules"]}
    assert status["C01"] == "fail" and status["C02"] == "fail" and status["C03"] == "fail"


def test_policy_exclusions_are_matched_against_conditions_and_add_ons():
    policy = {"exclusions": ["Cosmetic surgery", "Dental (non-accidental)", "Obesity surgery unless medically indicated"]}
    hits = compliance.exclusion_matches(policy, ["Dental cover requested", "Obesity"])
    assert {h["exclusion"] for h in hits} == {"Dental (non-accidental)", "Obesity surgery unless medically indicated"}
    report = compliance.evaluate(_ctx(policy=policy, submission={"channel": "live_session", "consent": True, "add_ons": "dental"}))
    assert next(r for r in report["rules"] if r["id"] == "C06")["status"] == "attention"


# --- layered confidence and graded outcomes -----------------------------------------------------------------------------------

def test_layers_report_margin_to_the_nearest_band_edge():
    near = outcome.layered_confidence(evidence=0.9, overall_risk=29.5, discrepancy_score=0)
    far = outcome.layered_confidence(evidence=0.9, overall_risk=12, discrepancy_score=0)
    assert near["margin"] < 0.2 and far["margin"] == 1.0 and near["overall"] < far["overall"]


def test_outcome_levels():
    layers = {"evidence": 0.9, "margin": 1.0}
    kw = dict(security=[], discrepancy_score=0, layers=layers, sum_insured=500000)
    assert outcome.grade(blocking=[], mandatory=[], **kw) == "straight_through"
    assert outcome.grade(blocking=["Agent 2 confidence 0.5 is below 0.70."], mandatory=[], **kw) == "full_review"
    assert outcome.grade(blocking=["x"], mandatory=["Mandatory review: y"], **kw) == "senior_referral"
    assert outcome.grade(blocking=[], mandatory=[], **{**kw, "security": ["quarantined"]}) == "senior_referral"
    close = {**kw, "layers": {"evidence": 0.9, "margin": 0.1}, "sum_insured": 2_000_000}
    assert outcome.grade(blocking=[], mandatory=[], **close) == "assisted_review"
    assert outcome.grade(blocking=[], mandatory=[], **{**close, "sum_insured": 300000}) == "straight_through"


def test_reason_codes_carry_an_owner_and_an_action():
    codes = outcome.reason_codes(["Mandatory review: Serious condition not declared: heart disease",
                                  "Agent 2 confidence 0.40 is below 0.70."])
    assert [c["code"] for c in codes] == ["SERIOUS_UNDECLARED", "LOW_CONFIDENCE"]
    assert all(c["owner"] and c["action"] for c in codes)


def test_customer_message_never_exposes_internal_detail():
    for level in ("straight_through", "assisted_review", "full_review", "senior_referral"):
        msg = outcome.customer_message(level, "accept_with_loading", 10, ["Latest HbA1c report"])
        text = " ".join([msg["headline"], msg["reason"], *msg["next_steps"]]).lower()
        assert not any(w in text for w in ("score", "fraud", "discrepan", "mandatory", "confidence", "flag"))
    assert "10%" in outcome.customer_message("straight_through", "accept_with_loading", 10, [])["reason"]


# --- cost guard -----------------------------------------------------------------------------------------------------------------------

def test_cost_guard_stops_a_runaway_case_and_resets_per_run():
    cost_guard.reset("CASE-X")
    assert all(cost_guard.allow("CASE-X") for _ in range(8))
    assert cost_guard.allow("CASE-X") is False
    assert cost_guard.allow("CASE-Y") is True  # other cases are unaffected
    cost_guard.reset("CASE-X")
    assert cost_guard.allow("CASE-X") is True