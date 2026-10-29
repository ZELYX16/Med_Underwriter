"""
Evidence states: positive, negative or unknown.

Failing to retrieve evidence is *unknown*, never proof of a negative. Only an
explicit statement counts as negative (the proposal says no admissions, the
insurer's schedule lists no claims, the policy states "Declared claims: None").
Scoring, protective factors, confidence and the review checks all use these
states so that missing documents are not mistaken for clean history.

Pure Python, no I/O.
"""
from __future__ import annotations

import re
from typing import Any

POSITIVE, NEGATIVE, UNKNOWN = "positive", "negative", "unknown"

DOMAINS = ("claims", "hospitalizations", "policy", "medical", "regulatory")


def _text(items: Any) -> str:
    out = []
    for item in items or []:
        if isinstance(item, dict):
            out.append(str(item.get("content") or item.get("text") or ""))
        else:
            out.append(str(item))
    return " ".join(out)


def _state(state: str, basis: str) -> dict[str, str]:
    return {"state": state, "basis": basis}


def evidence_states(
    *,
    profile: dict[str, Any],
    structured: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, dict[str, str]]:
    structured = structured or {}
    sub = structured.get("submission") or {}
    questionnaire = sub.get("questionnaire") or []
    policy_text = _text(evidence.get("policy_evidence")).lower()
    medical_text = _text(evidence.get("medical_evidence")).lower()
    claims_text = _text(evidence.get("claims_evidence")).lower()

    states: dict[str, dict[str, str]] = {}

    # --- claims -------------------------------------------------------------
    declared_claims = [c for c in (profile.get("claims") or []) if c]
    records = structured.get("claim_records") or []
    insurance = (sub.get("insurance") or [{}])[0] if sub.get("insurance") else {}
    claims_declared = str(insurance.get("claims_declared", "")).lower()
    if records or declared_claims or evidence.get("claims_evidence"):
        states["claims"] = _state(POSITIVE, "claim records or declared claims are on file")
    elif (
        re.search(r"\b(no|nil|none|0)\b[^.]{0,20}claims?", claims_declared)
        or re.search(r"declared claims:\s*(none|nil)|no (prior |previous )?claims", policy_text + " " + claims_text)
    ):
        states["claims"] = _state(NEGATIVE, "the proposal or policy explicitly states no claims")
    else:
        states["claims"] = _state(UNKNOWN, "no claims evidence was retrieved; this is not treated as zero claims")

    # --- hospitalizations ---------------------------------------------------------------
    hospitalizations = [h for h in (profile.get("hospitalizations") or []) if h]
    discharge_docs = [
        d for d in structured.get("documents", [])
        if "discharge" in str(d.get("title", "")).lower()
    ]
    asked_admission = any(
        re.search(r"hospital|admission|surgery", str(q.get("question", "")), re.I)
        and str(q.get("answer", "")).strip().lower() == "yes"
        for q in questionnaire
    )
    if hospitalizations or discharge_docs or asked_admission:
        states["hospitalizations"] = _state(POSITIVE, "hospital admissions are declared or documented")
    elif questionnaire:
        states["hospitalizations"] = _state(
            NEGATIVE, "the proposal's medical questionnaire lists no admission or surgery"
        )
    elif re.search(r"no (previous |prior )?(hospitali[sz]ation|admission)", medical_text):
        states["hospitalizations"] = _state(NEGATIVE, "a medical document states no hospitalization")
    else:
        states["hospitalizations"] = _state(
            UNKNOWN, "no hospitalization evidence was retrieved; this is not treated as no admissions"
        )

    # --- policy -------------------------------------------------------------------------------
    existing = (profile.get("existing_policy") or {}).get("policy_id")
    if structured.get("policy") or evidence.get("policy_evidence"):
        states["policy"] = _state(POSITIVE, "an existing policy document is on file")
    elif not existing:
        states["policy"] = _state(NEGATIVE, "no existing policy was declared")
    else:
        states["policy"] = _state(
            UNKNOWN, f"policy {existing} is declared but its schedule was not retrieved; coverage was not assessed"
        )

    # --- medical ---------------------------------------------------------------------------------------
    if structured.get("diagnoses") or structured.get("vitals") or evidence.get("medical_evidence"):
        states["medical"] = _state(POSITIVE, "medical documents are on file")
    else:
        states["medical"] = _state(UNKNOWN, "no medical documents were retrieved")

    # --- regulatory knowledge (not applicant evidence) ------------------------------------------------------
    states["regulatory"] = (
        _state(POSITIVE, "regulatory references were retrieved")
        if evidence.get("regulatory_evidence")
        else _state(UNKNOWN, "no regulatory reference was retrieved; not assessed")
    )
    return states


def completeness(states: dict[str, dict[str, str]]) -> float:
    """Share of the applicant evidence domains whose state is known."""
    domains = ("claims", "hospitalizations", "policy", "medical")
    known = sum(1 for d in domains if states.get(d, {}).get("state") != UNKNOWN)
    return round(known / len(domains), 2)


def verification_items(
    states: dict[str, dict[str, str]],
    *,
    conditions_declared: bool,
    existing_policy_declared: bool,
    sum_insured: float | None,
    age: float | None,
    age_threshold: int = 45,
    sum_insured_threshold: float = 1_000_000,
) -> list[dict[str, Any]]:
    """Unknowns, each marked material only when it bears on the decision."""
    large = bool(
        (sum_insured and sum_insured >= sum_insured_threshold)
        or (age and age >= age_threshold)
    )
    items: list[dict[str, Any]] = []

    def add(domain: str, action: str, material: bool, why: str) -> None:
        if states.get(domain, {}).get("state") == UNKNOWN:
            items.append({"domain": domain, "action": action, "material": material, "why": why})

    add("claims", "Obtain the claims history (insurer record or signed declaration)", large,
        "claims history is unknown and the age or sum insured is high" if large else "claims history is unknown")
    add("policy", "Obtain the existing policy schedule", existing_policy_declared,
        "a policy is declared but not on file" if existing_policy_declared else "no policy declared")
    add("medical", "Obtain a medical examination or supporting reports", conditions_declared,
        "conditions are declared but no medical document is on file" if conditions_declared else "no medical document")
    add("hospitalizations", "Confirm hospitalization history", conditions_declared and large,
        "hospital history unknown with declared conditions" if conditions_declared else "hospital history unknown")
    return items