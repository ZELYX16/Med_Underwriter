"""
Deterministic consistency checks: *potential discrepancies*, not confirmed fraud.

Pure rules over data the pipeline already holds. No LLM call and no extra
retrieval, so it adds no tokens and ~milliseconds of latency.

What this module produces is a list of discrepancies for a human to verify.
Nothing here can confirm fraud: `fraud_confirmed` stays False unless a
reviewer sets it. Each finding says how serious it is:

  mandatory        the case must go to a human (a *serious* undeclared
                   condition, or a document that is not this applicant's)
  verification     a human should confirm before relying on it (material
                   missing information, undeclared smoking)
  verify           listed for the reviewer; the score decides, no routing
  note             worth knowing, carries no points

A condition that is undeclared is judged on severity, control, complications
and how complete the evidence is (see services/severity.py), so a controlled,
routine condition is a note for the reviewer, not a reason to escalate.

Two paths:
  structured  documents were read table-aware; conditions are compared by
              group (ICD first), identity is role-aware (group policies are
              compared on the insured member, never the employer).
  legacy      only free text exists; a condition counts only when it is
              stated as a diagnosis (not a family history, test or negation).
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from typing import Any

from app.services.medical_groups import (
    STRONG_GROUPS,
    declared_groups,
    group_label,
    text_group,
)
from app.services.severity import assess_conditions, assess_group

# Codes whose findings can require review. Kept for callers that only need
# the names; the decision itself is the finding's `requires_review` field.
MATERIAL_FLAG_CODES = {"undeclared_condition", "undeclared_smoker", "identity_mismatch"}

_WEIGHTS = {
    "undeclared_serious": 25,
    "undeclared_indeterminate": 10,
    "undeclared_moderate": 10,
    "undeclared_routine": 5,
    "undeclared_smoker": 15,
    "identity_mismatch": 30,
    "identity_name_only": 10,
    "age_inconsistency": 10,
    "claim_record_mismatch": 15,
    "claim_count_mismatch": 15,
    "duplicate_claim": 25,
}

# keyword -> label (legacy path). Matched against retrieved evidence text.
_CONDITION_TERMS: dict[str, str] = {
    "diabetes": "diabetes",
    "hypertension": "hypertension",
    "nstemi": "myocardial infarction (NSTEMI)",
    "myocardial infarction": "myocardial infarction",
    "heart attack": "heart attack",
    "stent": "coronary stent",
    "angioplasty": "angioplasty",
    "coronary": "coronary disease",
    "cardiac": "cardiac condition",
    "heart disease": "heart disease",
    "heart failure": "heart failure",
    "stroke": "stroke",
    "cancer": "cancer",
    "carcinoma": "cancer",
    "chronic kidney": "chronic kidney disease",
    "renal failure": "renal failure",
    "cirrhosis": "cirrhosis",
    "liver disease": "liver disease",
    "copd": "COPD",
    "asthma": "asthma",
    "rheumatoid": "rheumatoid arthritis",
    "hypothyroid": "hypothyroidism",
    "epilepsy": "epilepsy",
    "schizophrenia": "schizophrenia",
    "hiv": "HIV",
}

_NEGATION = re.compile(
    r"\b(no|not|without|denies|negative for|ruled out|normal|nil)\b[^.\n]{0,40}$",
    re.IGNORECASE,
)
# Words that make a mention a statement of diagnosis / treatment.
_DIAGNOSIS_CUE = re.compile(
    r"\b(diagnos\w*|history of|known case|suffers? from|treated (with|for)|on (treatment|medication)"
    r"|under treatment|since \d{4}|prescribed|taking|takes|admitted (for|with)|post[- ])\b",
    re.IGNORECASE,
)
_FAMILY = re.compile(
    r"\b(father|mother|parents?|sister|brother|siblings?|grand\w+|family history|uncle|aunt)\b",
    re.IGNORECASE,
)


def _text_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("content") or item.get("text") or "")
    return str(item or "")


def _num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


class _Builder:
    """Collects findings and derives the score / routing reasons."""

    def __init__(self) -> None:
        self.flags: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []

    def flag(
        self,
        code: str,
        points: int,
        detail: str,
        *,
        mandatory: bool = False,
        requires_review: bool = False,
        **extra: Any,
    ) -> None:
        severity = "mandatory" if mandatory else "verification" if requires_review else "verify"
        self.flags.append(
            {
                "code": code,
                "points": points,
                "detail": detail,
                "severity": severity,
                "mandatory": mandatory,
                "requires_review": mandatory or requires_review,
                **extra,
            }
        )

    def note(self, code: str, detail: str) -> None:
        self.notes.append({"code": code, "detail": detail, "severity": "note"})

    def result(self) -> dict[str, Any]:
        score = float(min(100, sum(f["points"] for f in self.flags)))
        level = "high" if score >= 60 else "medium" if score >= 30 else "low"
        mandatory = [f["detail"] for f in self.flags if f["mandatory"]]
        verification = [
            f["detail"] for f in self.flags if f["requires_review"] and not f["mandatory"]
        ]
        return {
            "fraud_risk_score": score,
            "fraud_risk_level": level,
            "fraud_flags": self.flags,
            "fraud_notes": self.notes,
            # Same findings under their honest name; confirmation is a human act.
            "discrepancies": self.flags,
            "fraud_confirmed": False,
            "mandatory_reasons": mandatory,
            "verification_reasons": verification,
        }


def _undeclared(builder: _Builder, a: dict[str, Any], where: str) -> dict[str, Any] | None:
    """Turn an assessment of an undeclared condition into a finding (or a note)."""
    label = a["label"]
    why = "; ".join(a["reasons"])
    tier = a["tier"]
    common = dict(
        condition=label, group=a["group"], tier=tier, control=a["control"],
        complications=a["complications"], missing=a["missing"], source=where,
    )
    if tier == "serious":
        builder.flag(
            "undeclared_condition", _WEIGHTS["undeclared_serious"],
            f"Serious condition not declared: {label} ({why}); documented in {where}.",
            mandatory=True, **common,
        )
    elif tier == "indeterminate" and a["material_missing"]:
        builder.flag(
            "undeclared_condition", _WEIGHTS["undeclared_indeterminate"],
            f"{label} is documented in {where} but not declared, and cannot be judged: "
            f"missing {', '.join(a['material_missing'])}.",
            requires_review=True, **common,
        )
    elif a["group"] in STRONG_GROUPS:
        key = "undeclared_moderate" if tier == "moderate" else "undeclared_routine"
        extra = f" Missing: {', '.join(a['missing'])}." if a["missing"] else ""
        builder.flag(
            "undeclared_condition", _WEIGHTS[key],
            f"{label} is documented in {where} but not declared; assessed as {tier}"
            f" ({why}). Verify with the applicant; no escalation on its own.{extra}",
            **common,
        )
    else:
        builder.note("documented_not_declared", f"{label} appears in {where} and is not declared (not a material condition).")
    return None


# ---------------------------------------------------------------------------
# Structured path
# ---------------------------------------------------------------------------

def _structured(
    profile: dict[str, Any],
    submission: dict[str, Any],
    features: dict[str, Any],
    facts: dict[str, Any],
) -> dict[str, Any]:
    b = _Builder()
    sub = facts.get("submission") or {}
    questionnaire = sub.get("questionnaire") or []
    declared = declared_groups(profile.get("medical_conditions") or [], questionnaire)

    # Evidence for every group seen, declared or documented.
    groups: dict[str, dict[str, Any]] = {}
    for d in facts.get("diagnoses", []):
        g = d["group"]
        if g == "other":
            continue
        info = groups.setdefault(g, {"text": "", "icd": [], "declared": g in declared,
                                     "sources": [], "onset_known": False})
        info["text"] += f" {d['diagnosis']} {d.get('comment', '')}"
        if d.get("icd"):
            info["icd"].append(d["icd"])
        if d.get("document_id") and d["document_id"] not in info["sources"]:
            info["sources"].append(d["document_id"])
    narrative = facts.get("narrative", "")
    for c in profile.get("medical_conditions") or []:
        text = " ".join(str(v) for v in c.values() if v) if isinstance(c, dict) else str(c)
        g = text_group(text)
        if g:
            info = groups.setdefault(g, {"text": "", "icd": [], "declared": True,
                                         "sources": [], "onset_known": False})
            info["declared"] = True
            info["text"] += f" {text}"
            if isinstance(c, dict) and c.get("year_diagnosed"):
                info["onset_known"] = True
    for info in groups.values():
        info["text"] += f" {narrative}"

    medications = list(facts.get("medications") or []) + list(profile.get("medications") or [])
    assessments = assess_conditions(
        groups=groups,
        vitals=facts.get("vitals"),
        labs=facts.get("labs"),
        medications=medications,
        age=profile.get("age") or sub.get("age"),
        sum_insured=sub.get("sum_insured") or submission.get("sum_insured"),
        bmi=(facts.get("vitals") or {}).get("bmi"),
    )

    for a in assessments:
        if a["declared"]:
            continue
        _undeclared(b, a, ", ".join(a["sources"]) or "the documents")

    # Smoking: documents say smoker, the proposal did not declare tobacco use.
    if facts.get("smoking") == "smoker":
        tobacco_declared = profile.get("smoker") is True or any(
            str(q.get("answer", "")).strip().lower() == "yes"
            and re.search(r"tobacco|smok|nicotine", str(q.get("question", "")), re.I)
            for q in questionnaire
        )
        if (questionnaire or profile.get("smoker") is False) and not tobacco_declared:
            b.flag(
                "undeclared_smoker", _WEIGHTS["undeclared_smoker"],
                "Medical documents describe the applicant as a smoker; tobacco use "
                "was not declared in the proposal.",
                requires_review=True,
            )

    # Identity: a document that is not this applicant's is held out and flagged.
    for doc in facts.get("documents", []):
        problems = doc.get("identity_problems") or []
        if problems:
            material = any(p.get("material") for p in problems)
            text = "; ".join(f"{p['field']} {p['found']} (proposal: {p['expected']})" for p in problems)
            b.flag(
                "identity_mismatch",
                _WEIGHTS["identity_mismatch"] if material else _WEIGHTS["identity_name_only"],
                f"{doc['document_id']} does not match the proposal: {text}. Its content was not "
                "used for this applicant until identity is confirmed.",
                mandatory=material, requires_review=True, source=doc["document_id"],
            )
        elif doc.get("role_note") and "Group" in doc["role_note"]:
            b.note("policy_identity", f"{doc['document_id']}: {doc['role_note']}")
    for issue in facts.get("age_issues", []):
        b.flag("age_inconsistency", _WEIGHTS["age_inconsistency"], issue)

    # Claim records against the insurer's schedule and the proposal.
    records = facts.get("claim_records", [])
    policy = facts.get("policy") or {}
    schedule = {c["claim_id"]: c for c in policy.get("claims", [])}
    for record in records:
        entry = schedule.get(record["claim_id"])
        if not entry:
            continue
        problems = []
        if (
            record.get("approved") is not None and entry.get("approved") is not None
            and abs(record["approved"] - entry["approved"]) > 1
        ):
            problems.append(
                f"approved amount {record['approved']:,.0f} vs {entry['approved']:,.0f} on the policy schedule"
            )
        if record.get("event_date") and entry.get("start_date") and record["event_date"] != entry["start_date"]:
            problems.append(f"event date {record['event_date']} vs {entry['start_date']} on the policy schedule")
        if problems:
            b.flag("claim_record_mismatch", _WEIGHTS["claim_record_mismatch"],
                   f"{record['claim_id']}: " + "; ".join(problems) + ".", source=record["claim_id"])

    declared_text = (sub.get("insurance") or [{}])[0].get("claims_declared", "") if sub.get("insurance") else ""
    declared_match = re.search(r"(\d+)\s+claims?\s+declared", declared_text, re.IGNORECASE)
    if declared_match and schedule and int(declared_match.group(1)) != len(schedule):
        b.flag("claim_count_mismatch", _WEIGHTS["claim_count_mismatch"],
               f"The proposal declares {declared_match.group(1)} claim(s); the insurer's schedule lists {len(schedule)}.")

    keyed = Counter(
        (r.get("event_date"), r.get("approved"))
        for r in records if r.get("event_date") and r.get("approved")
    )
    if any(count > 1 for count in keyed.values()):
        b.flag("duplicate_claim", _WEIGHTS["duplicate_claim"],
               "Two claim records share the same event date and approved amount.")

    for claim_id in sub.get("claim_ids", []):
        if claim_id not in {r["claim_id"] for r in records}:
            b.note("claim_record_missing", f"Declared claim {claim_id} has no claim record on file.")

    total = len(schedule) or len(records)
    if total >= 4:
        cutoff = (date.today() - timedelta(days=365 * 3)).isoformat()
        recent = sum(1 for c in (policy.get("claims") or []) if c.get("start_date") and c["start_date"] >= cutoff)
        recent_text = f"; {recent} in the last 36 months" if schedule else ""
        b.note("claim_pattern", f"{total} claims on record{recent_text}. Declared and consistent with insurer records.")

    result = b.result()
    result["condition_assessments"] = assessments
    return result


# ---------------------------------------------------------------------------
# Legacy (free-text) path
# ---------------------------------------------------------------------------

def _mentions(text: str, term: str) -> str | None:
    """Window of text where `term` is stated as the applicant's diagnosis."""
    for match in re.finditer(re.escape(term), text, re.IGNORECASE):
        before = text[max(0, match.start() - 60): match.start()]
        window = text[max(0, match.start() - 120): match.end() + 120]
        sentence_start = max(
            text.rfind(".", 0, match.start()), text.rfind(";", 0, match.start()), text.rfind("\n", 0, match.start())
        )
        sentence = text[sentence_start + 1: match.end() + 60]
        if _NEGATION.search(before) or _FAMILY.search(sentence):
            continue
        if _DIAGNOSIS_CUE.search(window):
            return window
    return None


_CLAIM_LINE = re.compile(
    r"(CLM-\d{5})[^\n]*?(\d{4}-\d{2}-\d{2})[^\n]*?(?:INR|Rs\.?)\s*([\d,]+)",
    re.IGNORECASE,
)


def _claims_from_text(text: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    claims: list[dict[str, Any]] = []
    for claim_id, claim_date, amount in _CLAIM_LINE.findall(text):
        claim_id = claim_id.upper()
        if claim_id in seen:
            continue
        seen.add(claim_id)
        claims.append({"claim_id": claim_id, "date": claim_date, "amount": amount.replace(",", "")})
    return claims


def _legacy(
    profile: dict[str, Any],
    submission: dict[str, Any],
    features: dict[str, Any],
    high_sum_insured: float,
) -> dict[str, Any]:
    b = _Builder()
    declared = declared_groups(list(features.get("conditions") or []), None)
    declared_text = " ".join(
        str(c).lower()
        for c in (list(features.get("conditions") or []) + list(features.get("medications") or []))
    )
    evidence_text = " ".join(
        _text_of(item)
        for key in ("medical_evidence", "claims_evidence")
        for item in (features.get(key) or [])
    )
    age = features.get("age")
    sum_insured = _num(features.get("sum_insured"))

    handled: set[str] = set()
    for term, label in _CONDITION_TERMS.items():
        group = text_group(term) or term
        if group in handled or group in declared or term in declared_text or label.lower() in declared_text:
            continue
        window = _mentions(evidence_text, term)
        if window is None:
            if re.search(re.escape(term), evidence_text, re.IGNORECASE):
                handled.add(group)
                b.note("keyword_mention", f"Documents mention {label}; not stated as a diagnosis, so not treated as non-disclosure.")
            continue
        handled.add(group)
        assessment = assess_group(group, text=window)
        assessment["label"] = label
        assessment["declared"] = False
        assessment["sources"] = []
        assessment["material_missing"] = assessment["missing"] if (
            (age and age >= 45) or sum_insured >= 1_000_000
        ) else []
        _undeclared(b, assessment, "the retrieved documents")

    smoker = profile.get("smoker")
    declared_non_smoker = smoker in (False, "False", "false", "no", "No", 0)
    if declared_non_smoker and re.search(
        r"\b(current smoker|smokes|tobacco use|cigarette)\b", evidence_text, re.IGNORECASE
    ):
        if not re.search(r"\b(non[- ]?smoker|never smoked|quit)\b", evidence_text, re.IGNORECASE):
            b.flag("undeclared_smoker", _WEIGHTS["undeclared_smoker"],
                   "Applicant declared non-smoker but documents indicate tobacco use.", requires_review=True)

    claims = [c for c in (features.get("claims") or []) if isinstance(c, dict)]
    claim_count = int(features.get("claim_count", len(claims)) or 0)
    if not any(c.get("amount") or c.get("claim_amount") for c in claims):
        parsed = _claims_from_text(" ".join(_text_of(i) for i in (features.get("claims_evidence") or [])))
        if parsed:
            claims = parsed
            claim_count = max(claim_count, len(parsed))

    if claim_count >= 4:
        b.note("claim_pattern", f"{claim_count} prior claims on record.")
    dates = [str(c.get("claim_date") or c.get("date") or "")[:7] for c in claims]
    month_counts = Counter(d for d in dates if d)
    if month_counts and max(month_counts.values()) >= 2:
        month = max(month_counts, key=month_counts.get)
        b.note("claim_cluster", f"Multiple claims fall in the same month ({month}).")
    signatures = Counter(
        (str(c.get("claim_date") or c.get("date") or ""), str(c.get("amount") or c.get("claim_amount") or ""))
        for c in claims if c.get("amount") or c.get("claim_amount")
    )
    if any(count > 1 for count in signatures.values()):
        b.flag("duplicate_claim", _WEIGHTS["duplicate_claim"], "Two claims share the same date and amount.")

    claimed = sum(_num(c.get("amount") or c.get("claim_amount")) for c in claims)
    if sum_insured > 0 and claimed > 0.5 * sum_insured:
        b.note("claims_vs_cover", "Prior claimed amounts exceed half of the requested sum insured.")
    if sum_insured >= high_sum_insured and int(features.get("condition_count", 0) or 0) >= 2:
        b.note("high_cover", "High sum insured requested with multiple medical conditions.")

    return b.result()


def assess_fraud(
    applicant_profile: dict[str, Any],
    submission: dict[str, Any],
    features: dict[str, Any],
    high_sum_insured: float = 5_000_000.0,
) -> dict[str, Any]:
    facts = features.get("structured") or {}
    if facts.get("available"):
        return _structured(applicant_profile, submission, features, facts)
    return _legacy(applicant_profile, submission, features, high_sum_insured)