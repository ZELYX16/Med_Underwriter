"""Deterministic, evidence-aware applicant clarification engine.

Questions are generated only for material gaps, conflicting evidence, or facts
whose extraction confidence is too low for safe use. No LLM calls are made.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

LOW_CONFIDENCE_THRESHOLD = 0.75

# The fact types here are produced by document_pipeline.process_document.
_CONDITION_RULES: dict[str, dict[str, Any]] = {
    "diabetes": {
        "facts": {"hba1c"},
        "questions": [
            ("diagnosis_year", "When were you first diagnosed with diabetes?", "text",
             "The diagnosis date helps establish how long the condition has been present."),
            ("complications", "Has a doctor ever told you that diabetes affected your eyes, kidneys, nerves or feet?", "yes_no_unsure",
             "This helps us understand whether there are documented complications."),
            ("hba1c", "Do you know your most recent HbA1c result?", "text",
             "We could not find a recent HbA1c result in the documents provided."),
        ],
    },
    "bp": {
        "facts": set(),
        "questions": [
            ("bp_reading", "What was your most recent blood pressure reading, if known?", "text",
             "A recent reading helps us understand how the condition is controlled."),
            ("complications", "Have you been told that high blood pressure affected your heart, kidneys, eyes or brain?", "yes_no_unsure",
             "This helps identify any known complications."),
        ],
    },
    "heart": {
        "facts": {"diagnosis_text", "admission_date", "discharge_date"},
        "questions": [
            ("event_details", "Please tell us which heart condition or procedure you had (for example, heart attack, stent or bypass) and approximately when.", "text",
             "The uploaded documents do not clearly establish the event and its date."),
            ("current_status", "Are you currently under follow-up or taking medication for this heart condition?", "yes_no_unsure",
             "Current treatment status is important to understand the condition."),
        ],
    },
    "kidney": {
        "facts": {"creatinine", "egfr"},
        "questions": [
            ("kidney_type", "Is this kidney stones, chronic kidney disease, or another kidney condition?", "choice",
             "The type of kidney condition is not clear from the information provided.", ["Kidney stones", "Chronic kidney disease", "Another kidney condition", "Not sure"]),
            ("kidney_status", "Have you had any recent kidney function tests (such as creatinine or eGFR)?", "yes_no_unsure",
             "Recent kidney function information may be needed to assess the condition."),
        ],
    },
    "cancer": {
        "facts": {"diagnosis_text"},
        "questions": [
            ("cancer_type", "What type of cancer were you diagnosed with, and approximately when?", "text",
             "The cancer type and diagnosis date are material to the assessment."),
            ("treatment_status", "Is treatment ongoing, completed, or is the condition under follow-up?", "choice",
             "We need to understand the current treatment status.", ["Treatment ongoing", "Treatment completed", "Under follow-up", "Not sure"]),
        ],
    },
    "stroke": {
        "facts": {"diagnosis_text", "admission_date", "discharge_date"},
        "questions": [
            ("event_date", "Approximately when did the stroke or mini-stroke occur?", "text",
             "The event date is not clear from the information provided."),
            ("residual_effects", "Do you currently have any ongoing effects or treatment related to it?", "yes_no_unsure",
             "Current effects can change the information needed for assessment."),
        ],
    },
}

_GENERIC_CONDITION_QUESTIONS = [
    ("diagnosis_and_treatment", "When were you diagnosed, and are you currently receiving treatment or taking medication for this condition?", "text",
     "The diagnosis timeline and current treatment status are not clear from the information provided."),
]


def _answers(form: dict[str, Any]) -> dict[str, Any]:
    value = form.get("clarification_answers") or {}
    return value if isinstance(value, dict) else {}


def _has_answer(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip().casefold()
    return normalized not in {"", "— select an answer —", "select an answer", "please select"}

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "diagnosis_year": ("diagnosis_year", "since", "year", "year_diagnosed"),
    "bp_reading": ("bp_reading", "reading", "bp", "blood_pressure"),
    "kidney_type": ("kidney_type", "kind", "type", "condition_type"),
    "event_details": ("event_details", "event", "details", "procedure"),
    "cancer_type": ("cancer_type", "kind", "type", "stage"),
    "hba1c": ("hba1c", "reading", "value", "latest_hba1c"),
    "complications": ("complications", "any_complications", "complication"),
}


def _get_condition_answer(answers_dict: dict[str, Any], field: str) -> Any:
    aliases = FIELD_ALIASES.get(field, (field,))
    for alias in aliases:
        val = answers_dict.get(alias)
        if _has_answer(val):
            return val
    return None



def _question(
    *, question_id: str, category: str, question: str, input_type: str,
    reason: str, condition_key: str | None = None, options: list[str] | None = None,
    blocking: bool = True, evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    upload_category = {
        "medical_condition": "medical",
        "hospital_history": "medical",
        "claims_history": "claims",
        "policy_history": "policy",
        "fact_confirmation": "medical",
        "evidence_conflict": "medical",
    }.get(category)
    return {
        "id": question_id,
        "kind": "clarification",
        "upload_category": upload_category,
        "upload_label": (
            "Upload a medical report or doctor's note" if upload_category == "medical"
            else "Upload the relevant supporting document" if upload_category else None
        ),
        "category": category,
        "condition_key": condition_key,
        "question": question,
        "text": question,
        "input_type": input_type,
        "options": options or [],
        "reason": reason,
        "blocking": blocking,
        "evidence": evidence or [],
    }


def _facts(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for doc in documents or []:
        if doc.get("status") in {"rejected", "failed", "deleting", "delete_failed"}:
            continue
        for fact in doc.get("extracted_facts") or []:
            if not isinstance(fact, dict):
                continue
            facts.append({
                **fact,
                "filename": doc.get("filename", "Uploaded document"),
                "document_id": doc.get("id"),
            })
    return facts


def _fact_matches(facts: list[dict[str, Any]], fact_types: set[str]) -> list[dict[str, Any]]:
    return [f for f in facts if str(f.get("fact_type", "")) in fact_types]


def build_clarifications(form: dict[str, Any], documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return unanswered material questions plus non-blocking review items."""
    form = form or {}
    answers = _answers(form)
    facts = _facts(documents)
    output: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["id"] in seen_ids:
            return
        seen_ids.add(item["id"])
        answer = answers.get(item["id"])
        if _has_answer(answer):
            item["answer"] = answer
            item["answered"] = True
            normalized_answer = str(answer).strip().lower()
            if ("not sure" in normalized_answer or "reviewer" in normalized_answer
                    or normalized_answer in {"not_sure", "unsure"}):
                item["blocking"] = False
                item["needs_human_review"] = True
                item["status"] = "needs_review"
                output.append(item)
            elif str(answer).strip().lower() in {"no, correct it", "incorrect"}:
                correction_id = item["id"] + "_correction"
                correction = _question(
                    question_id=correction_id, category="fact_correction",
                    question="Please enter the correct information, if known.", input_type="text",
                    reason="You indicated that the extracted information is incorrect.",
                    condition_key=item.get("condition_key"), evidence=item.get("evidence"),
                )
                if not _has_answer(answers.get(correction_id)):
                    output.append(correction)
            return
        item["answered"] = False
        output.append(item)

    # Applicant-declared medical conditions: ask only for material fields not
    # already found in uploaded evidence or explicitly answered.
    for condition in form.get("conditions") or []:
        if not isinstance(condition, dict):
            continue
        key = str(condition.get("key") or "custom")
        label = str(condition.get("label") or "this condition")
        answers_for_condition = condition.get("answers") or {}
        rule = _CONDITION_RULES.get(key)
        questions = rule["questions"] if rule else _GENERIC_CONDITION_QUESTIONS
        relevant_types = (rule.get("facts", set()) if rule else set()) | {"diagnosis_text"}
        relevant = _fact_matches(facts, relevant_types)
        facts_text = " ".join(str(f.get("value", "")) for f in relevant).casefold()

        for spec in questions:
            field, prompt, input_type, reason, *extra = spec
            # Skip a field when its explicit evidence is already available.
            if field == "hba1c" and any(f.get("fact_type") == "hba1c" for f in facts):
                continue
            if field == "bp_reading":
                if any(f.get("fact_type") == "blood_pressure" for f in facts):
                    continue
                # Intake stores applicant PDFs first and extracts them when
                # underwriting starts. Do not ask for a duplicate BP report
                # while a relevant uploaded medical document is still pending.
                pending_medical_evidence = any(
                    str(doc.get("status", "")).lower() in {"accepted", "indexing", "indexed", "needs_review"}
                    and str(doc.get("detected_type", "")).lower() in {
                        "medical_exam", "lab", "specialist", "prescription", "discharge"
                    }
                    for doc in (documents or [])
                )
                if pending_medical_evidence:
                    continue
            if field == "kidney_status" and any(f.get("fact_type") in {"creatinine", "egfr"} for f in facts):
                continue
            if field == "kidney_type" and re.search(r"kidney stone|renal calcul|chronic kidney disease|\bckd\b", facts_text):
                continue
            if field == "event_details" and re.search(r"stent|bypass|myocardial infarction|heart attack|angioplasty|\bcabg\b", facts_text):
                continue
            if field == "cancer_type" and re.search(r"carcinoma|lymphoma|leukaemia|leukemia|sarcoma|melanoma|myeloma", facts_text):
                continue
            if field == "event_date" and any(f.get("fact_type") in {"admission_date", "discharge_date"} for f in relevant):
                continue
            if field == "complications" and re.search(r"no (known )?complication|without complication|complications? (nil|none|absent)|retinopathy|nephropathy|neuropathy|end[- ]organ damage", facts_text):
                continue
            # If the diagnosis itself is in a document, avoid asking generic
            # diagnosis-year questions unless the date is still missing.
            if field == "diagnosis_year" and relevant and re.search(r"\b(19|20)\d{2}\b", facts_text):
                continue
            if _get_condition_answer(answers_for_condition, field) is not None:
                continue
            qid = f"condition:{key}:{field}"
            add(_question(
                question_id=qid, category="medical_condition", condition_key=key,
                question=f"{prompt} ({label})" if key == "custom" else prompt,
                input_type=input_type, reason=reason,
                options=extra[0] if extra else [],
                evidence=[{"filename": f.get("filename"), "page": f.get("page"),
                           "value": f.get("value"), "excerpt": f.get("excerpt")}
                          for f in relevant[:3]],
            ))

    # Yes declarations need a minimal description; do not ask if the applicant
    # has already supplied it in the form.
    if str(form.get("hospital_stay", "")).lower() == "yes" and not str(form.get("hospital_details") or "").strip():
        add(_question(question_id="history:hospital_details", category="hospital_history",
                      question="Please tell us the approximate year and reason for your hospital stay.",
                      input_type="text", reason="You declared a hospital stay, but its basic details are missing."))
    if str(form.get("had_claims", "")).lower() == "yes" and not str(form.get("claims_details") or "").strip():
        add(_question(question_id="history:claims_details", category="claims_history",
                      question="Please briefly describe the claim (approximate year, reason and outcome, if known).",
                      input_type="text", reason="You declared a previous claim, but its basic details are missing."))
    if str(form.get("has_other_insurance", "")).lower() == "yes" and not str(form.get("previous_insurance_details") or "").strip():
        add(_question(question_id="history:previous_policy", category="policy_history",
                      question="Please provide the previous insurer and policy details, if known.",
                      input_type="text", reason="You declared another policy, but its details are missing."))

    # Ask for applicant confirmation only where extraction confidence is low.
    confirmable_types = {"patient_name", "patient_dob", "diagnosis_text", "hba1c", "glucose",
                         "creatinine", "blood_pressure", "medication_text", "admission_date", "discharge_date"}
    low_confidence_count = 0
    for fact in facts:
        if fact.get("fact_type") not in confirmable_types or low_confidence_count >= 5:
            continue
        try:
            confidence = float(fact.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence >= LOW_CONFIDENCE_THRESHOLD:
            continue
        stable = hashlib.sha1(
            f"{fact.get('document_id')}|{fact.get('fact_type')}|{fact.get('page')}|{fact.get('value')}".encode("utf-8")
        ).hexdigest()[:10]
        add(_question(
            question_id=f"fact:{stable}", category="fact_confirmation",
            question=f"We read '{fact.get('value', 'this detail')}' from {fact.get('filename', 'your document')}. Is this correct?",
            input_type="confirmation", reason="The document text was not clear enough to rely on without confirmation.",
            options=["Yes, this is correct", "No, correct it", "Not sure — reviewer should verify"],
            evidence=[{"filename": fact.get("filename"), "page": fact.get("page"),
                       "value": fact.get("value"), "excerpt": fact.get("excerpt")}],
        ))
        low_confidence_count += 1

    # Conflicting same-date values must be explicitly reconciled or sent to a
    # human reviewer. We never choose one value automatically.
    for doc in documents or []:
        if doc.get("status") in {"rejected", "failed", "deleting", "delete_failed"}:
            continue
        for conflict in doc.get("conflicts") or []:
            stable = hashlib.sha1(
                f"{conflict.get('fact_type')}|{conflict.get('date')}|{conflict.get('current_value')}|{conflict.get('previous_value')}".encode("utf-8")
            ).hexdigest()[:10]
            add(_question(
                question_id=f"conflict:{stable}", category="evidence_conflict",
                question=(f"Two documents show different {conflict.get('fact_type', 'test')} values for "
                          f"{conflict.get('date')}: {conflict.get('current_value')} and {conflict.get('previous_value')}. "
                          "Which information should we use?"),
                input_type="confirmation", reason="The records disagree for the same test and date.",
                options=[f"Use {conflict.get('current_value')} from this document",
                         f"Use {conflict.get('previous_value')} from {conflict.get('previous_document', 'the earlier document')}",
                         "Not sure — reviewer should verify"],
                evidence=[{"filename": doc.get("filename"), "value": conflict.get("current_value"),
                           "date": conflict.get("date")},
                          {"filename": conflict.get("previous_document"), "value": conflict.get("previous_value"),
                           "date": conflict.get("date")}],
            ))

    return output


def clarification_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = [i for i in items if i.get("blocking")]
    review = [i for i in items if i.get("needs_human_review")]
    return {
        "total": len(items),
        "unanswered": len(blocking),
        "needs_human_review": len(review),
        "ready": not blocking,
    }