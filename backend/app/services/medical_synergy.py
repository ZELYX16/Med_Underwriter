"""
Medical Synergy & Actuarial Rating Engine:
Implements baseline mortality lookup (IALM 2012-14 Ultimate), numerical debits rating,
multivariate copula comorbidity interaction multipliers, and statutory PED waiting periods.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.state import PEDWaitingPeriod

_TABLE_PATH = Path(__file__).resolve().parent.parent / "data" / "ialm_mortality_table.json"
_MORTALITY_TABLE: dict[str, Any] | None = None


def get_mortality_table() -> dict[str, Any]:
    global _MORTALITY_TABLE
    if _MORTALITY_TABLE is None:
        if _TABLE_PATH.exists():
            with open(_TABLE_PATH, "r", encoding="utf-8") as f:
                _MORTALITY_TABLE = json.load(f)
        else:
            _MORTALITY_TABLE = {"male": {}, "female": {}}
    return _MORTALITY_TABLE


def get_baseline_mortality(age: int, gender: str) -> float:
    """
    Returns the single-year biological age baseline mortality rate (q_x)
    from IALM 2012-14 Ultimate. Ages clamped to 18..75.
    """
    table = get_mortality_table()
    sex_key = "female" if str(gender or "").strip().lower() in {"f", "female", "woman"} else "male"
    sex_table = table.get(sex_key, {})

    clamped_age = max(18, min(75, int(age or 35)))
    age_str = str(clamped_age)

    if age_str in sex_table:
        return float(sex_table[age_str])

    # Fallback default if table missing
    return 0.001282 if sex_key == "male" else 0.001045


def calculate_actuarial_premium(
    sum_insured: float,
    age: int,
    gender: str,
    extra_mortality_percentage: float,
    expense_load: float = 0.20,
) -> dict[str, Any]:
    """
    Computes pure risk premium and loaded final premium based on actuarial principles.
    P_base = Sum Insured * q_x * (1 + Expense Load)
    Loading % = max(0.0, EMP - 100.0)
    P_final = P_base * (1.0 + Loading % / 100.0)
    """
    qx = get_baseline_mortality(age, gender)
    si = max(100_000.0, float(sum_insured or 500_000.0))

    base_premium = round(si * qx * (1.0 + expense_load), 2)
    loading_pct = max(0.0, round(float(extra_mortality_percentage or 100.0) - 100.0, 2))
    final_premium = round(base_premium * (1.0 + (loading_pct / 100.0)), 2)

    return {
        "base_premium": base_premium,
        "loading_percentage": loading_pct,
        "final_premium": final_premium,
        "qx": qx,
        "expense_load": expense_load,
    }


def calculate_numerical_rating(
    features: dict[str, Any],
    applicant_profile: dict[str, Any] | None = None,
    submission: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Computes individual debits, applies Copula interaction multipliers,
    and returns actuarial debits, extra mortality percentage (EMP),
    and calibrated medical risk score (0-100).
    """
    profile = applicant_profile or {}
    sub = submission or {}

    declared_conditions = profile.get("medical_conditions") or features.get("conditions") or []
    undeclared_conditions = features.get("undeclared_conditions") or []
    condition_assessments = features.get("condition_assessments") or []
    assessment_map = {a.get("group"): a for a in condition_assessments if isinstance(a, dict)}

    debits_breakdown: list[dict[str, Any]] = []
    base_debits = 0.0

    # 1. Condition debits
    seen_groups = set()

    all_cond_items = []
    for c in declared_conditions:
        if isinstance(c, dict):
            all_cond_items.append({"name": c.get("condition", ""), "group": c.get("group"), "declared": True})
        else:
            all_cond_items.append({"name": str(c), "group": None, "declared": True})

    for u in undeclared_conditions:
        if isinstance(u, dict):
            all_cond_items.append({"name": u.get("label", ""), "group": u.get("group"), "declared": False})
        else:
            all_cond_items.append({"name": str(u), "group": None, "declared": False})

    for item in all_cond_items:
        name = str(item["name"]).lower()
        group = item["group"] or ""
        tag = f"{group or name}_{item['declared']}"
        if tag in seen_groups:
            continue
        seen_groups.add(tag)

        debit = 0.0
        reason = ""

        # Assessment details if available
        assessment = assessment_map.get(group)
        is_controlled = (assessment.get("control") == "controlled") if assessment else False

        if "diabet" in name or group == "diabetes":
            debit = 20.0 if is_controlled else 35.0
            reason = "Type 2 Diabetes (controlled: 20, standard: 35)"
        elif "hypertens" in name or "blood pressure" in name or group == "hypertension":
            debit = 10.0 if is_controlled else 20.0
            reason = "Hypertension (controlled: 10, standard: 20)"
        elif any(k in name for k in ["heart", "cardiac", "stent", "coronary", "nstemi", "bypass", "angina"]) or group == "cardiac":
            debit = 50.0
            reason = "Coronary Artery / Cardiac Disease (50 debits)"
        elif any(k in name for k in ["kidney", "renal", "ckd"]) or group == "renal":
            debit = 60.0
            reason = "Chronic Kidney Disease (60 debits)"
        elif "cancer" in name or "carcinoma" in name or group == "cancer":
            debit = 75.0
            reason = "Malignant Neoplasm (75 debits)"
        elif any(k in name for k in ["copd", "respiratory"]) or group == "respiratory":
            debit = 35.0
            reason = "Chronic Respiratory Disease / COPD (35 debits)"
        elif "asthma" in name:
            debit = 15.0
            reason = "Bronchial Asthma (15 debits)"
        elif any(k in name for k in ["stroke", "cerebrovascular"]) or group == "cerebrovascular":
            debit = 60.0
            reason = "Cerebrovascular Disease / Stroke (60 debits)"
        elif "liver" in name or "cirrhosis" in name or group == "liver":
            debit = 40.0
            reason = "Chronic Liver Disease (40 debits)"
        elif group == "urinary_calculi" or "stone" in name:
            debit = 10.0
            reason = "Urinary Calculi (10 debits)"
        elif group == "thyroid" or "thyroid" in name:
            debit = 5.0
            reason = "Thyroid Disorder (5 debits)"
        else:
            debit = 10.0
            reason = f"Medical condition: {name}"

        if not item["declared"]:
            debit += 10.0
            reason += " [Undeclared penalty +10]"

        base_debits += debit
        debits_breakdown.append({"item": name, "group": group, "debits": debit, "reason": reason})

    # 2. Lifestyle / Smoking
    is_smoker = profile.get("smoker") is True or features.get("smoker") is True
    if is_smoker:
        base_debits += 25.0
        debits_breakdown.append({"item": "smoker", "debits": 25.0, "reason": "Tobacco use / Smoker (25 debits)"})

    # 3. BMI / Obesity
    bmi = profile.get("bmi") or features.get("bmi")
    is_obese = False
    if bmi:
        try:
            bmi_val = float(bmi)
            if bmi_val >= 40.0:
                base_debits += 60.0
                is_obese = True
                debits_breakdown.append({"item": "severe_obesity", "debits": 60.0, "reason": f"Class 3 Obesity (BMI {bmi_val} >= 40)"})
            elif bmi_val >= 35.0:
                base_debits += 40.0
                is_obese = True
                debits_breakdown.append({"item": "moderate_obesity", "debits": 40.0, "reason": f"Class 2 Obesity (BMI {bmi_val} >= 35)"})
            elif bmi_val >= 30.0:
                base_debits += 20.0
                is_obese = True
                debits_breakdown.append({"item": "mild_obesity", "debits": 20.0, "reason": f"Class 1 Obesity (BMI {bmi_val} >= 30)"})
        except (ValueError, TypeError):
            pass

    # 4. Occupation Hazard Class
    occ_prof = profile.get("occupation_profile") or features.get("occupation_profile") or {}
    hazard_class = occ_prof.get("hazard_class", 1)
    try:
        hc_int = int(hazard_class)
    except (ValueError, TypeError):
        hc_int = 1

    occ_debit = 0.0
    if hc_int == 2:
        occ_debit = 10.0
    elif hc_int == 3:
        occ_debit = 25.0
    elif hc_int >= 4:
        occ_debit = 50.0

    if occ_debit > 0:
        base_debits += occ_debit
        debits_breakdown.append({
            "item": "occupation_hazard",
            "debits": occ_debit,
            "reason": f"Hazard Class {hc_int} ({occ_prof.get('title', 'Occupation')})",
        })

    # 5. Family Medical History
    fam_hist = profile.get("family_medical_history") or profile.get("family_history") or []
    fam_debits = 0.0
    for fh in fam_hist:
        if isinstance(fh, dict):
            rel = str(fh.get("relation", "")).lower()
            cond = str(fh.get("condition", "")).lower()
            onset = fh.get("age_at_onset")
            if rel in {"father", "mother", "sibling", "parent"}:
                is_serious = any(k in cond for k in ["heart", "cardiac", "stroke", "cancer", "diabetes"])
                early_onset = onset is None or int(onset) < 55
                if is_serious and early_onset:
                    fam_debits += 15.0
                    debits_breakdown.append({
                        "item": f"family_history_{rel}",
                        "debits": 15.0,
                        "reason": f"Early-onset (<55) {cond} in 1st degree relative ({rel})",
                    })
    fam_debits = min(30.0, fam_debits)
    base_debits += fam_debits

    # 6. Copula Synergy Multipliers
    has_diabetes = any(d.get("group") == "diabetes" or "diabet" in d["item"] for d in debits_breakdown)
    has_hypertension = any(d.get("group") == "hypertension" or "hypertens" in d["item"] or "blood pressure" in d["item"] for d in debits_breakdown)
    has_cardiac = any(d.get("group") == "cardiac" or any(k in d["item"] for k in ["cardiac", "heart", "coronary", "cad", "stent", "angina", "bypass", "nstemi"]) for d in debits_breakdown)
    has_renal = any(d.get("group") == "renal" or any(k in d["item"] for k in ["kidney", "renal", "ckd", "nephro"]) for d in debits_breakdown)
    has_respiratory = any(d.get("group") == "respiratory" or any(k in d["item"] for k in ["respiratory", "copd", "asthma", "pulmonary", "bronch"]) for d in debits_breakdown)

    active_synergies = []
    if has_diabetes and has_hypertension and is_obese:
        active_synergies.append({
            "name": "Metabolic Syndrome Triad",
            "multiplier": 1.45,
            "description": "Compounded vascular and glycemic risk from T2D, HTN, and Obesity (BMI >= 30)",
        })
    if has_cardiac and has_renal:
        active_synergies.append({
            "name": "Cardiorenal Syndrome",
            "multiplier": 2.10,
            "description": "Accelerated end-organ mortality multiplier from concurrent CAD/CHF and CKD",
        })
    if has_respiratory and is_smoker:
        active_synergies.append({
            "name": "Respiratory Multimorbidity",
            "multiplier": 1.75,
            "description": "Synergistic pulmonary degradation from chronic respiratory disease and tobacco use",
        })

    if active_synergies:
        synergy_multiplier = max(s["multiplier"] for s in active_synergies)
    else:
        synergy_multiplier = 1.0

    synergy_interaction_debits = round(base_debits * (synergy_multiplier - 1.0), 2)
    total_actuarial_debits = round(base_debits * synergy_multiplier, 2)
    extra_mortality_percentage = round(100.0 + total_actuarial_debits, 2)

    # Calibrate medical risk score to 0..100 scale: min(100.0, debits * 0.5)
    calibrated_medical_score = min(100.0, round(total_actuarial_debits * 0.5, 2))

    return {
        "raw_debits": base_debits,
        "synergy_multiplier": synergy_multiplier,
        "synergy_interaction_debits": synergy_interaction_debits,
        "actuarial_debits": total_actuarial_debits,
        "extra_mortality_percentage": extra_mortality_percentage,
        "medical_risk_score": calibrated_medical_score,
        "active_synergies": active_synergies,
        "debits_breakdown": debits_breakdown,
    }


def generate_ped_waiting_periods(
    conditions: list[Any],
    condition_assessments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Generates Pre-Existing Disease (PED) waiting periods compliant with
    IRDAI 2024 regulations (maximum 36 months statutory cap).
    """
    assessments = {a.get("group"): a for a in (condition_assessments or []) if isinstance(a, dict)}
    results: list[dict[str, Any]] = []
    seen = set()

    for item in conditions or []:
        c_name = item.get("condition") if isinstance(item, dict) else str(item)
        if not c_name or c_name.lower() in seen:
            continue
        seen.add(c_name.lower())

        group = item.get("group") if isinstance(item, dict) else None
        assessment = assessments.get(group)

        # Permanent exclusion for uninsurable conditions
        is_malignant_active = "metastatic" in c_name.lower() or "active cancer" in c_name.lower()
        if is_malignant_active:
            ped = PEDWaitingPeriod(
                condition=c_name,
                waiting_period_months=0,
                statutory_cap_months=36,
                permanent_exclusion=True,
            )
        else:
            is_controlled = assessment.get("control") == "controlled" if assessment else False
            months = 24 if is_controlled else 36
            ped = PEDWaitingPeriod(
                condition=c_name,
                waiting_period_months=min(36, months),
                statutory_cap_months=36,
                permanent_exclusion=False,
            )
        results.append(ped.model_dump())

    return results
