from __future__ import annotations


"""
Live intake: what to ask, what is still needed, and how the form becomes a case.

Everything here is deterministic and costs no tokens. Questions are written in
everyday words; the clinical term is only used internally. An LLM is used (by
the caller, behind the cost guard) only to map a typed condition that the
lookup could not recognise.
"""

import re
from datetime import date
from typing import Any

from app.services.extraction import parse_number
from app.services.medical_groups import text_group


def _c(key, label, group, clinical, extra, docs):
    # Medical attributes are extracted from evidence first. The applicant only
    # declares the condition here; material gaps are handled by clarification.
    return {
        "key": key,
        "label": label,
        "group": group,
        "clinical": clinical,
        "followups": extra or [],
        "documents": docs,
    }


CONDITIONS: list[dict[str, Any]] = [
    _c("diabetes", "Diabetes (high sugar)", "diabetes", "Diabetes mellitus",
       [{"id": "reading", "ask": "Your latest sugar test result (HbA1c), if you know it", "type": "text"},
        {"id": "complications", "ask": "Any problems with eyes, kidneys, feet or nerves because of sugar?", "type": "yesno"}],
       ["Latest blood sugar / HbA1c lab report"]),
    _c("bp", "High blood pressure", "hypertension", "Hypertension",
       [{"id": "reading", "ask": "Your most recent blood pressure reading (for example 128/82)", "type": "text"}],
       ["Recent blood pressure readings or doctor's note"]),
    _c("heart", "Heart problem (heart attack, stent, bypass, angina)", "cardiac", "Heart disease",
       [{"id": "event", "ask": "Did you have a heart attack, a stent or a bypass? Which, and which year?", "type": "text"}],
       ["Hospital discharge summary or cardiology report"]),
    _c("cholesterol", "High cholesterol", "lipids", "Dyslipidaemia", [], []),
    _c("thyroid", "Thyroid problem", "thyroid", "Thyroid disorder", [], []),
    _c("asthma", "Asthma or breathing problem", "respiratory", "Chronic respiratory disease", [], []),
    _c("kidney", "Kidney problem (stones or kidney disease)", "urinary_calculi", "Kidney / urinary condition",
       [{"id": "kind", "ask": "Is it kidney stones or kidney disease?", "type": "choice",
         "options": ["Kidney stones", "Kidney disease", "Not sure"]}],
       ["Latest kidney function report or discharge summary"]),
    _c("liver", "Liver problem", "liver", "Liver disease", [], ["Liver function report"]),
    _c("cancer", "Cancer (now or in the past)", "cancer", "Cancer",
       [{"id": "kind", "ask": "Which type, and when was your last treatment?", "type": "text"}],
       ["Treatment summary or latest oncology report"]),
    _c("stroke", "Stroke or mini-stroke", "cerebrovascular", "Cerebrovascular disease", [], ["Discharge summary or neurology report"]),
    _c("joint", "Joint, back or spine problem", "spine", "Spine / joint disorder", [], []),
    _c("digestive", "Acidity, ulcer or stomach problem", "gi", "Digestive disorder", [], []),
    _c("mental", "Depression, anxiety or other mental-health condition", "mental_health", "Mental-health condition", [], []),
    _c("neuro", "Fits (epilepsy) or migraine", "neurological", "Neurological condition", [], []),
]
BY_KEY = {c["key"]: c for c in CONDITIONS}

_SYNONYMS = {
    "sugar": "diabetes", "diabetic": "diabetes", "t2dm": "diabetes",
    "bp": "bp", "htn": "bp", "pressure": "bp", "hypertension": "bp",
    "stent": "heart", "bypass": "heart", "angina": "heart", "heart": "heart", "cardiac": "heart", "nstemi": "heart",
    "stone": "kidney", "kidney": "kidney", "renal": "kidney",
    "cholesterol": "cholesterol", "thyroid": "thyroid", "asthma": "asthma", "copd": "asthma",
    "liver": "liver", "jaundice": "liver", "cancer": "cancer", "tumour": "cancer", "tumor": "cancer",
    "stroke": "stroke", "paralysis": "stroke", "back": "joint", "spine": "joint", "arthritis": "joint", "knee": "joint",
    "acidity": "digestive", "gerd": "digestive", "ulcer": "digestive", "gastric": "digestive",
    "depression": "mental", "anxiety": "mental", "epilepsy": "neuro", "migraine": "neuro", "fits": "neuro",
}

PRODUCTS = ["MedShield Comprehensive", "MedShield Essential", "MedShield Family Floater"]
MEDICAL_EXAM_AGE = 45
MEDICAL_EXAM_SUM = 1_000_000


def lookup_condition(text: str) -> dict[str, Any]:
    """Map a typed condition to the catalogue without any LLM call."""
    clean_text = str(text or "").lower().strip()
    # Check text_group first (catches multi-word medical patterns like "high blood pressure")
    group = text_group(clean_text)
    if group:
        c = next((c for c in CONDITIONS if c["group"] == group), None)
        if c:
            return {"key": c["key"], "label": c["label"], "group": group, "matched": True}
    # Check synonyms with longest keys first
    for syn in sorted(_SYNONYMS.keys(), key=len, reverse=True):
        pattern = rf"(?<!\w){re.escape(syn)}(?!\w)"
        if re.search(pattern, clean_text):
            c = BY_KEY[_SYNONYMS[syn]]
            return {"key": c["key"], "label": c["label"], "group": c["group"], "matched": True}
    return {"key": None, "label": str(text).strip().title(), "group": None, "matched": False}


def age_from_dob(dob: str | None, today: date | None = None) -> int | None:
    try:
        born = date.fromisoformat(str(dob))
    except (TypeError, ValueError):
        return None
    t = today or date.today()
    return t.year - born.year - ((t.month, t.day) < (born.month, born.day))


def selected_conditions(form: dict[str, Any]) -> list[dict[str, Any]]:
    """Ticked catalogue conditions plus typed ones, each with its answers."""
    out = []
    for item in form.get("conditions", []):
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        base = BY_KEY.get(key) or {}
        label = item.get("label") or base.get("label") or str(key or "Other condition").replace("_", " ").title()
        answers = item.get("answers") if isinstance(item.get("answers"), dict) else {}
        out.append({
            **item,
            "key": key,
            "label": label,
            "group": item.get("group") or base.get("group"),
            "clinical": base.get("clinical") or item.get("clinical") or label,
            "answers": answers,
        })
    return out


def required_documents(form: dict[str, Any]) -> list[dict[str, Any]]:
    """What the applicant must attach, from the form alone (no pipeline run)."""
    age = age_from_dob(form.get("dob")) or form.get("age") or 0
    cover = float(form.get("sum_insured") or 0)
    conditions = selected_conditions(form)
    needs = []
    reasons = []
    if age and age >= MEDICAL_EXAM_AGE:
        reasons.append(f"you are {age}")
    if cover >= MEDICAL_EXAM_SUM:
        reasons.append("the cover amount is high")
    if reasons:
        needs.append({"id": "medical_exam", "document": "Recent medical check-up report",
                      "why": "We ask for this because " + " and ".join(reasons) + ".",
                      "blocking": True, "type": "medical"})
    for c in conditions:
        for i, doc in enumerate(BY_KEY.get(c.get("key"), {}).get("documents", [])):
            needs.append({"id": f"{c['key']}_{i}", "document": doc,
                          "why": f"Helps us understand your {c['label'].lower()} quickly.",
                          "blocking": False, "type": "medical"})
    if _yes(form.get("has_other_insurance")):
        needs.append({"id": "policy", "document": "Your current policy document", "why": "You told us you have another health policy.",
                      "blocking": False, "type": "policy"})
    if _yes(form.get("had_claims")):
        needs.append({"id": "claims", "document": "Claim records or settlement letters", "why": "You told us about earlier claims.",
                      "blocking": False, "type": "claims"})
    return needs


def open_items(form: dict[str, Any], documents: list[dict[str, Any]],
               clarifications: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """What is still missing, in plain words. Blocking items stop submission."""
    items: list[dict[str, Any]] = []
    for fid, text in (("name", "Your full name"), ("dob", "Your date of birth"), ("sex", "Your sex"),
                      ("product", "Which plan you want"), ("sum_insured", "How much cover you want")):
        if not form.get(fid):
            items.append({"id": fid, "kind": "field", "text": text, "blocking": True})
    for q in ("hospital_stay", "had_claims", "has_other_insurance", "smoker"):
        if form.get(q) in (None, ""):
            items.append({"id": q, "kind": "field", "blocking": True, "text": {
                "hospital_stay": "Have you stayed in hospital in the last 5 years? (yes or no)",
                "had_claims": "Have you made any health-insurance claim before? (yes or no)",
                "has_other_insurance": "Do you have another health policy? (yes or no)",
                "smoker": "Do you smoke or use tobacco? (yes or no)"}[q]})
    if not form.get("consent"):
        items.append({"id": "consent", "kind": "confirmation", "blocking": True,
                      "text": "Please confirm that the details are true and that we may use them to assess your application"})
    later = set(form.get("docs_later") or [])
    live = [d for d in documents if d.get("status") not in {"rejected", "failed", "deleting", "delete_failed"}]
    attached = {d.get("requirement") for d in live}
    detected_folders = {d.get("folder") for d in live}
    detected_types = {d.get("detected_type") for d in live}
    has_exam = "medical_exam" in detected_types
    for need in required_documents(form):
        medical_types = {"medical_exam", "lab", "specialist", "prescription", "discharge"}
        inferred_match = (
            (need["id"] == "policy" and ("policy" in detected_folders or "policy" in detected_types))
            or (need["id"] == "claims" and ("claims" in detected_folders or "claim" in detected_types))
            or (need["id"].startswith("bp_") and bool(detected_types & medical_types))
            or (need["id"].startswith("diabetes_") and bool(detected_types & {"lab", "medical_exam", "specialist"}))
        )
        if need["id"] in attached or inferred_match or (need["id"] == "medical_exam" and has_exam):
            continue
        if need["id"] in later:
            items.append({"id": need["id"], "kind": "document", "blocking": False, "later": True,
                          "text": f"{need['document']} (you said you will add this later)"})
        else:
            items.append({"id": need["id"], "kind": "document", "blocking": need["blocking"],
                          "text": f"{need['document']}. {need['why']}"})

    # Evidence-aware questions are generated only for material gaps,
    # uncertain extraction and conflicting source records.
    if clarifications is None:
        from app.services.clarification_engine import build_clarifications
        clarifications = build_clarifications(form, documents)
    for question in clarifications:
        if question.get("answered") and not question.get("needs_human_review"):
            continue
        items.append({
            **question,
            "kind": "clarification",
            "text": question.get("question", "Please provide more information."),
        })
    return items


def to_profile_submission(applicant_id: str, form: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Turn the form into the same profile / submission the pipeline already uses."""
    conditions = selected_conditions(form)
    meds, hospitals = [], []
    for c in conditions:
        a = c.get("answers", {})
        for m in re.split(r"[;,\n]", str(a.get("medicines") or "")):
            if m.strip():
                meds.append({"name": m.strip().title(), "details": "", "indication": c.get("label", "")})
        if str(a.get("hospital") or "").strip():
            hospitals.append({"details": a["hospital"].strip(), "reason": c.get("label", "")})
    if str(form.get("hospital_details") or "").strip():
        hospitals.append({"details": form["hospital_details"].strip(), "reason": "Declared hospital stay"})
    height, weight = form.get("height_cm"), form.get("weight_kg")
    bmi = round(weight / ((height / 100) ** 2), 1) if height and weight else form.get("bmi")
    alcohol_value = str(form.get("alcohol_consumption") or "").strip().lower()
    alcohol_normalized = {
        "never": "none",
        "occasionally": "occasional",
        "regularly": "regular",
        "prefer not to say": "not_disclosed",
    }.get(alcohol_value, alcohol_value or None)
    clarification_answers = form.get("clarification_answers", {}) or {}
    clarification_review_required = any(
        ("not sure" in str(value).strip().lower()
         or "reviewer" in str(value).strip().lower()
         or str(value).strip().lower() in {"not_sure", "unsure"})
        for value in clarification_answers.values()
    ) if isinstance(clarification_answers, dict) else False
    profile = {
        "applicant_id": applicant_id,
        "name": form.get("name"),
        "date_of_birth": form.get("dob"),
        "age": age_from_dob(form.get("dob")),
        "sex": form.get("sex"),
        "gender": form.get("sex"),
        "email": form.get("email"),
        "phone": form.get("phone"),
        "address": form.get("address"),
        "occupation": form.get("occupation"),
        "smoker": _yes(form.get("smoker")),
        "alcohol_consumption": form.get("alcohol_consumption"),
        "alcohol_use": alcohol_normalized,
        "family_members": form.get("family_members", []) or [],
        "bmi": bmi,
        "source": "live_session",
        "medical_conditions": [
            {
                "condition": c["clinical"],
                "group": c.get("group"),
                "year_diagnosed": _year(c.get("answers", {}).get("since")),
                "status": "; ".join(
                    f"{k.replace('_', ' ')}: {v}"
                    for k, v in c.get("answers", {}).items()
                    if v and k not in {"since"}
                ),
                "details": dict(c.get("answers", {})),
            }
            for c in conditions
        ],
        "medications": meds,
        "hospitalizations": hospitals,
        "claims": ([
            {
                "details": str(form.get("claims_details") or "Declared previous claim"),
                "claim_count": form.get("claim_count"),
                "claim_status": form.get("claim_status"),
                "claim_year": form.get("claim_year"),
            }
        ] if _yes(form.get("had_claims")) else []),
        "applicant_clarifications": clarification_answers,
        "clarification_review_required": clarification_review_required,
        "existing_policy": ({
            "policy_id": form.get("previous_policy_number") or "DECLARED",
            "insurer": form.get("previous_insurer"),
            "sum_insured": form.get("previous_policy_cover"),
            "expiry_date": form.get("previous_policy_expiry"),
            "details": form.get("previous_insurance_details") or "",
        } if _yes(form.get("has_other_insurance")) else {}),
        "declarations": {
            "no_hospital_admission": str(form.get("hospital_stay")).lower() == "no" and not hospitals,
            "no_claims": str(form.get("had_claims")).lower() == "no",
        },
    }
    submission = {
        "product": form.get("product"),
        "policy_type": form.get("policy_type") or "Individual",
        "sum_insured": int(parse_number(form.get("sum_insured"))) if parse_number(form.get("sum_insured")) > 0 else None,
        "deductible": int(parse_number(form.get("deductible"))) if parse_number(form.get("deductible")) > 0 else None,
        "term_years": int(form.get("term_years") or 1),
        "family_members": form.get("family_members", []) or [],
        "previous_insurance_details": form.get("previous_insurance_details") or "",
        "jurisdiction": "India",
        "insurer": "DEMO_INSURER",
        "consent": bool(form.get("consent")),
        "applicant_remarks": form.get("remarks") or "",
        "applicant_clarifications": clarification_answers,
        "clarification_review_required": clarification_review_required,
        "channel": "live_session",
    }
    return profile, submission


def _yes(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "y", "1"}


def _year(value: Any) -> int | None:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group()) if match else None
