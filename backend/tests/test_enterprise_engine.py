"""
Unit & Integration Tests for Enterprise Medical Underwriting Engine:
- IALM 2012-14 Ultimate single-year mortality baseline lookup
- Reverse Pharmacotherapy inference and contextual exceptions (e.g. Metformin in PCOS)
- Multivariate Copula Comorbidity Multipliers (Metabolic, Cardiorenal, Respiratory)
- Actuarial pricing formulas & scale separation invariant
- IRDAI 2024 statutory Pre-Existing Disease (PED) waiting periods
- 4-Tier review gating & backward compatibility aliases
"""
from __future__ import annotations

import pytest

from app.models.state import (
    FamilyHistoryRecord,
    FamilyMemberRelation,
    OccupationHazardClass,
    OccupationHazardRecord,
    MedicationVerificationItem,
    PEDWaitingPeriod,
    LabAnalyteRecord,
)
from app.services.medical_synergy import (
    get_baseline_mortality,
    calculate_actuarial_premium,
    calculate_numerical_rating,
    generate_ped_waiting_periods,
)
from app.services.reverse_pharmacotherapy import (
    verify_medications,
    normalize_drug_name,
)
from app.services.review_gate import evaluate_review_gate


# ---------------------------------------------------------------------------
# 1. Domain Models & Pydantic Schemas
# ---------------------------------------------------------------------------
def test_pydantic_domain_schemas():
    fam = FamilyHistoryRecord(
        relation=FamilyMemberRelation.FATHER,
        condition="Coronary Artery Disease",
        age_at_onset=48,
    )
    assert fam.relation == "father"
    assert fam.age_at_onset == 48

    occ = OccupationHazardRecord(
        title="Offshore Oil Rig Technician",
        hazard_class=OccupationHazardClass.CLASS_4,
    )
    assert occ.hazard_class == 4

    med = MedicationVerificationItem(
        drug_name="Metformin 500mg",
        inferred_condition="diabetes_type2",
        is_declared=True,
        discrepancy_score=0,
        context_exception_applied=True,
        context_exception_tag="Metformin for PCOS",
    )
    assert med.context_exception_applied

    ped = PEDWaitingPeriod(
        condition="Hypertension",
        waiting_period_months=24,
        statutory_cap_months=36,
    )
    assert ped.waiting_period_months <= ped.statutory_cap_months

    lab = LabAnalyteRecord(
        analyte_name="HbA1c",
        measured_value=7.4,
        measured_unit="%",
        normalized_value=7.4,
        normalized_unit="%",
        reference_high=6.5,
        is_abnormal=True,
    )
    assert lab.is_abnormal


# ---------------------------------------------------------------------------
# 2. IALM 2012-14 Baseline Mortality Lookup
# ---------------------------------------------------------------------------
def test_ialm_mortality_lookup():
    # Male mortality rates
    q_m_25 = get_baseline_mortality(25, "M")
    q_m_45 = get_baseline_mortality(45, "male")
    q_m_65 = get_baseline_mortality(65, "M")

    assert 0.0005 < q_m_25 < 0.0015
    assert 0.002 < q_m_45 < 0.004
    assert 0.010 < q_m_65 < 0.020
    assert q_m_25 < q_m_45 < q_m_65

    # Female mortality rates (typically lower than male for same age)
    q_f_45 = get_baseline_mortality(45, "female")
    assert q_f_45 < q_m_45

    # Age clamping
    q_clamped_low = get_baseline_mortality(10, "M")
    assert q_clamped_low == get_baseline_mortality(18, "M")

    q_clamped_high = get_baseline_mortality(90, "F")
    assert q_clamped_high == get_baseline_mortality(75, "F")


# ---------------------------------------------------------------------------
# 3. Reverse Pharmacotherapy Disambiguation
# ---------------------------------------------------------------------------
def test_reverse_pharmacotherapy_pcos_context_exception():
    # Female applicant taking Metformin with declared PCOS
    verified = verify_medications(
        prescriptions=[{"drug_name": "Metformin 500mg"}],
        declared_conditions=[{"condition": "Polycystic Ovarian Disease (PCOS)", "group": "other"}],
        applicant_sex="female",
    )
    assert len(verified) == 1
    item = verified[0]
    assert item["is_declared"] is True
    assert item["discrepancy_score"] == 0
    assert item["context_exception_applied"] is True
    assert "PCOS" in (item["context_exception_tag"] or "")


def test_reverse_pharmacotherapy_undeclared_cardiovascular_drug():
    # Applicant taking Clopidogrel but no CAD/heart declared
    verified = verify_medications(
        prescriptions=[{"name": "Clopidogrel 75mg"}],
        declared_conditions=[],
        applicant_sex="male",
    )
    assert len(verified) == 1
    item = verified[0]
    assert item["is_declared"] is False
    assert item["discrepancy_score"] >= 40
    assert any(k in item["inferred_condition"] for k in ["cad", "cardiac", "coronary"])


def test_reverse_pharmacotherapy_declared_diabetes():
    # Applicant taking Glimepiride with declared T2D
    verified = verify_medications(
        prescriptions=["Glimepiride 2mg"],
        declared_conditions=[{"condition": "Type 2 Diabetes", "group": "diabetes"}],
        applicant_sex="male",
    )
    assert len(verified) == 1
    assert verified[0]["is_declared"] is True
    assert verified[0]["discrepancy_score"] == 0


# ---------------------------------------------------------------------------
# 4. Copula Synergy & Actuarial Debits Engine
# ---------------------------------------------------------------------------
def test_copula_metabolic_syndrome_triad():
    # T2D + HTN + Obesity (BMI >= 30) -> Phi = 1.45
    rating = calculate_numerical_rating(
        features={
            "conditions": [
                {"condition": "Type 2 Diabetes Mellitus", "group": "diabetes"},
                {"condition": "Essential Hypertension", "group": "hypertension"},
            ],
            "bmi": 32.5,
            "smoker": False,
        },
        applicant_profile={
            "bmi": 32.5,
            "smoker": False,
        },
    )
    assert rating["synergy_multiplier"] == 1.45
    assert any(s["name"] == "Metabolic Syndrome Triad" for s in rating["active_synergies"])
    assert rating["synergy_interaction_debits"] > 0
    assert rating["extra_mortality_percentage"] > 150.0
    # Scale separation invariant: calibrated medical risk score must remain <= 100.0
    assert rating["medical_risk_score"] <= 100.0


def test_copula_cardiorenal_syndrome():
    # CAD + CKD -> Phi = 2.10
    rating = calculate_numerical_rating(
        features={
            "conditions": [
                {"condition": "Coronary Artery Disease with prior stent", "group": "cardiac"},
                {"condition": "Chronic Kidney Disease Stage 3", "group": "renal"},
            ],
            "bmi": 24.0,
            "smoker": False,
        },
        applicant_profile={
            "bmi": 24.0,
            "smoker": False,
        },
    )
    assert rating["synergy_multiplier"] == 2.10
    assert any(s["name"] == "Cardiorenal Syndrome" for s in rating["active_synergies"])
    assert rating["extra_mortality_percentage"] >= 200.0


def test_copula_respiratory_multimorbidity():
    # COPD + Smoker -> Phi = 1.75
    rating = calculate_numerical_rating(
        features={
            "conditions": [
                {"condition": "Chronic Obstructive Pulmonary Disease", "group": "respiratory"},
            ],
            "bmi": 23.0,
            "smoker": True,
        },
        applicant_profile={
            "bmi": 23.0,
            "smoker": True,
        },
    )
    assert rating["synergy_multiplier"] == 1.75
    assert any(s["name"] == "Respiratory Multimorbidity" for s in rating["active_synergies"])


# ---------------------------------------------------------------------------
# 5. Actuarial Pricing & IRDAI PED Waiting Periods
# ---------------------------------------------------------------------------
def test_actuarial_pricing_calculation():
    # Clean 35 yo male with EMP = 100% (standard life)
    p_std = calculate_actuarial_premium(
        sum_insured=1_000_000.0,
        age=35,
        gender="male",
        extra_mortality_percentage=100.0,
    )
    assert p_std["loading_percentage"] == 0.0
    assert p_std["final_premium"] == p_std["base_premium"]

    # 45 yo male with EMP = 175% (+75% loading)
    p_sub = calculate_actuarial_premium(
        sum_insured=1_000_000.0,
        age=45,
        gender="male",
        extra_mortality_percentage=175.0,
    )
    assert p_sub["loading_percentage"] == 75.0
    assert p_sub["final_premium"] == round(p_sub["base_premium"] * 1.75, 2)


def test_ped_waiting_period_statutory_cap():
    periods = generate_ped_waiting_periods(
        conditions=[
            {"condition": "Controlled Hypertension", "group": "hypertension"},
            {"condition": "Type 2 Diabetes Mellitus", "group": "diabetes"},
            {"condition": "Metastatic Adenocarcinoma", "group": "cancer"},
        ],
        condition_assessments=[
            {"group": "hypertension", "control": "controlled"},
            {"group": "diabetes", "control": "uncontrolled"},
        ],
    )
    by_cond = {p["condition"]: p for p in periods}

    # Controlled HTN -> 24 months
    assert by_cond["Controlled Hypertension"]["waiting_period_months"] == 24
    assert by_cond["Controlled Hypertension"]["statutory_cap_months"] == 36

    # Uncontrolled T2D -> 36 months (statutory cap)
    assert by_cond["Type 2 Diabetes Mellitus"]["waiting_period_months"] == 36

    # Metastatic condition -> permanent exclusion
    assert by_cond["Metastatic Adenocarcinoma"]["permanent_exclusion"] is True
    assert by_cond["Metastatic Adenocarcinoma"]["waiting_period_months"] == 0


# ---------------------------------------------------------------------------
# 6. Centralized Review Gate 4-Tier Calibration
# ---------------------------------------------------------------------------
def test_review_gate_four_tiers():
    # Tier 0: Clean STP
    gate_0 = evaluate_review_gate({
        "medical_risk_score": 15.0,
        "overall_risk_score": 25.0,
        "agent2_confidence": 0.88,
        "fraud_risk_score": 0.0,
        "reflection_verdict": "pass",
    })
    assert gate_0["review_tier"] == "Tier 0"
    assert not gate_0["requires_human_review"]
    assert gate_0["review_level"] == "straight_through"

    # Tier 1: Fast-track review (minor discrepancy or low confidence)
    gate_1 = evaluate_review_gate({
        "medical_risk_score": 25.0,
        "overall_risk_score": 35.0,
        "agent2_confidence": 0.62,
    })
    assert gate_1["review_tier"] == "Tier 1"
    assert gate_1["requires_human_review"]
    assert gate_1["review_level"] == "assisted_review"

    # Tier 2: Comprehensive Medical Review (overall risk >= 70 or fraud discrepancy >= 50)
    gate_2 = evaluate_review_gate({
        "medical_risk_score": 60.0,
        "overall_risk_score": 72.0,
        "agent2_confidence": 0.85,
    })
    assert gate_2["review_tier"] == "Tier 2"
    assert gate_2["requires_human_review"]
    assert gate_2["review_level"] == "full_review"

    # Tier 3: Chief Medical Officer Escalation (medical risk >= 80 or security flag)
    gate_3 = evaluate_review_gate({
        "medical_risk_score": 85.0,
        "overall_risk_score": 65.0,
        "agent2_confidence": 0.85,
        "security_review_reasons": ["Aadhaar photo mismatch"],
    })
    assert gate_3["review_tier"] == "Tier 3"
    assert gate_3["requires_human_review"]
    assert gate_3["review_level"] == "full_review"
