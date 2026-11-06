"""
Compliance catalogue: explicit, versioned checks with a per-case report.

Each rule has an id, a source label, a plain statement, and a deterministic
check that returns pass / fail / needs_info / attention / na with a reason.
Retrieved regulatory text is used for citation in the UI; the *decision* about
each rule comes from the catalogue, never from free-text retrieval.

The source labels are internal references to be confirmed with the compliance
function; they are not legal citations.
"""
from __future__ import annotations

import re
from typing import Any

CATALOGUE_VERSION = "2026.11"
_PROTECTED = ("gender", "sex", "religion", "race", "ethnicity", "caste", "marital", "nationality")
_GENERIC_EXCLUSIONS = {"war", "nuclear", "self-inflicted", "experimental", "cosmetic", "infertility"}


def exclusion_matches(policy: dict[str, Any] | None, texts: list[str]) -> list[dict[str, str]]:
    """Policy exclusions that touch a declared / documented condition or add-on."""
    if not policy:
        return []
    haystack = " ".join(texts).lower()
    found = []
    for exclusion in policy.get("exclusions", []):
        words = [w for w in re.findall(r"[a-z]{5,}", exclusion.lower())
                 if w not in {"unless", "medically", "indicated", "routine", "hospitalised", "non-accidental"}]
        hit = next((w for w in words if w in haystack), None)
        if hit and hit not in _GENERIC_EXCLUSIONS:
            found.append({"exclusion": exclusion, "applies_to": hit})
    return found


def evaluate(ctx: dict[str, Any]) -> dict[str, Any]:
    profile = ctx.get("profile") or {}
    submission = ctx.get("submission") or {}
    risk = ctx.get("risk") or {}
    flags = ctx.get("flags") or []
    policy = ctx.get("policy")
    states = risk.get("evidence_states") or {}
    live = submission.get("channel") == "live_session"
    codes = {f.get("code"): f for f in flags}
    rules: list[dict[str, str]] = []

    def add(rule_id: str, title: str, source: str, status: str, detail: str) -> None:
        rules.append({"id": rule_id, "title": title, "source": source, "status": status, "detail": detail})

    # C01 disclosure against documents
    if any(f.get("code") == "undeclared_condition" and f.get("mandatory") for f in flags):
        add("C01", "Declarations are consistent with the documents", "Duty of disclosure (internal policy)", "fail",
            "A serious condition in the documents was not declared; mandatory review.")
    elif states.get("medical", {}).get("state") == "unknown" and profile.get("medical_conditions"):
        add("C01", "Declarations are consistent with the documents", "Duty of disclosure (internal policy)", "needs_info",
            "No medical document was available to compare with the declaration.")
    else:
        add("C01", "Declarations are consistent with the documents", "Duty of disclosure (internal policy)", "pass",
            "No serious undeclared condition found.")

    # C02 consent
    add("C02", "Applicant consent recorded", "Data-protection consent (internal policy)",
        ("pass" if submission.get("consent") else "fail") if live else "na",
        "Consent was captured with the form." if submission.get("consent") else
        ("Consent is missing." if live else "Not a live application; consent captured in the proposal."))

    # C03 protected attributes
    text = " ".join(str(f) for f in risk.get("risk_factors", [])).lower()
    used = [a for a in _PROTECTED if a in text]
    add("C03", "Protected attributes are not risk factors", "Fair-treatment principle (internal policy)",
        "fail" if used else "pass", ("Used as a factor: " + ", ".join(used)) if used else "None used.")

    # C04 identity
    ident = [f for f in flags if f.get("code") == "identity_mismatch"]
    add("C04", "Documents belong to the applicant", "KYC / identity (internal policy)",
        "fail" if ident else ("pass" if ctx.get("has_documents") else "na"),
        ident[0]["detail"] if ident else ("Identity matched on every document." if ctx.get("has_documents") else "No documents to check."))

    # C05 waiting periods / pre-existing
    notes = risk.get("coverage_notes") or []
    policy_state = states.get("policy", {}).get("state")
    if policy_state == "unknown":
        add("C05", "Waiting-period and pre-existing position stated", "Policy terms (internal policy)", "needs_info",
            "A policy is declared but its schedule is not on file; coverage was not assessed.")
    else:
        add("C05", "Waiting-period and pre-existing position stated", "Policy terms (internal policy)", "pass",
            f"{len(notes)} policy note(s) recorded." if notes else "No existing policy terms apply.")

    # C06 exclusions
    texts = [str(c.get("condition", "")) for c in profile.get("medical_conditions", []) if isinstance(c, dict)]
    texts += [a.get("label", "") for a in risk.get("condition_assessments", []) if isinstance(a, dict)]
    texts += [str(submission.get("add_ons", "")), str(submission.get("applicant_remarks", ""))]
    matches = exclusion_matches(policy, texts)
    add("C06", "Policy exclusions considered", "Policy terms (internal policy)",
        "attention" if matches else ("pass" if policy else "na"),
        "; ".join(f"'{m['exclusion']}' may apply ({m['applies_to']})" for m in matches) if matches
        else ("No exclusion touches the declared conditions or add-ons." if policy else "No policy schedule to check."))

    # C07 adverse outcomes
    rec = str(ctx.get("recommendation", ""))
    adverse = rec in {"decline", "postpone"}
    add("C07", "Adverse outcomes are decided by a person", "Fair-treatment principle (internal policy)",
        "pass" if (not adverse or ctx.get("mandatory")) else "fail",
        "No adverse outcome proposed." if not adverse else "Adverse outcome routed to a person.")

    # C08 explainability
    add("C08", "Decision can be explained", "Explainability (internal policy)",
        "pass" if (risk.get("risk_factors") or risk.get("protective_factors")) else "needs_info",
        "Risk and protective factors are recorded.")

    # C09 evidence sufficiency
    material = [v for v in risk.get("verification_items", []) if v.get("material")]
    add("C09", "Evidence is sufficient for the decision", "Underwriting standard (internal policy)",
        "needs_info" if material else "pass",
        ("Missing: " + "; ".join(v["action"] for v in material)) if material else "No material evidence gap.")

    # C10 personal data and hosted models
    hosted = ctx.get("provider", "ollama") != "ollama"
    add("C10", "Personal data protected when models are hosted", "Data protection (internal policy)", "pass",
        "Prompts carry structured facts only (no name, ID or date of birth)."
        + (" A hosted provider is in use." if hosted else " A local model is in use."))

    summary: dict[str, int] = {}
    for r in rules:
        summary[r["status"]] = summary.get(r["status"], 0) + 1
    return {**catalogue_metadata(), "version": CATALOGUE_VERSION, "rules": rules, "summary": summary, "exclusions": matches}


def catalogue_metadata() -> dict[str, Any]:
    """Governance metadata for audit displays and exported reports.

    Catalogue source labels are internal policy references, not legal citations.
    Compliance owners must approve jurisdiction/product mapping before production.
    """
    return {
        "catalogue_version": CATALOGUE_VERSION,
        "catalogue_status": "internal_review_required",
        "source_status": "internal_policy_labels_not_legal_citations",
        "jurisdiction": "not_configured",
        "requires_compliance_owner_approval": True,
    }
