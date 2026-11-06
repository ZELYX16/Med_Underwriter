"""SQLite-backed applicant templates and folder-based document discovery.

The catalogue never embeds applicant records in Python. Applicant profiles and
submission details are read from SQLite; original supporting files remain in
the applicant's data folder and are only registered with the live session here.
No extraction, embedding or Chroma write happens when a template is selected.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
import hashlib

from app.config import settings
from app.services import intake

CATEGORY_ALIASES = {
    "medical": "medical", "medical_records": "medical",
    "medical_reports": "medical", "medical_exam": "medical",
    "health": "medical", "lab": "medical", "labs": "medical",
    "prescription": "medical", "prescriptions": "medical",
    "policy": "policy", "policies": "policy",
    "previous_policy": "policy", "insurance": "policy",
    "claims": "claims", "claim": "claims", "claim_records": "claims",
    "previous_claims": "claims", "claim_history": "claims",
}


def _iso_dob(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw[:10], fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return ""


def _yes(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value or "").strip().lower()
    return "yes" if text in {"yes", "true", "1", "y", "smoker", "current"} else "no"


def _category_for(path: Path, applicant_dir: Path) -> str | None:
    try:
        parts = [p.lower().replace(" ", "_") for p in path.relative_to(applicant_dir).parts[:-1]]
    except ValueError:
        return None
    # Most-specific matching folder wins; proposal/submission source PDFs are
    # deliberately not treated as customer supporting evidence.
    if any(p in {"underwriting", "proposal", "submission"} for p in parts):
        return None
    for part in reversed(parts):
        if part in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[part]
    return None


def discover_documents(applicant_id: str, root: Path | None = None) -> list[dict[str, Any]]:
    """Return safe metadata for supported files under one applicant folder."""
    base = (root or settings.synthetic_data_directory / "applicants").resolve()
    applicant_dir = (base / applicant_id).resolve()
    if applicant_dir.parent != base or not applicant_dir.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for path in sorted(applicant_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".txt", ".csv", ".json"}:
            continue
        category = _category_for(path, applicant_dir)
        if not category:
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(applicant_dir)
            stat = resolved.stat()
            digest = hashlib.sha256()
            with resolved.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            results.append({
                "filename": resolved.name,
                "document_type": category,
                "file_path": str(resolved),
                "relative_path": str(resolved.relative_to(applicant_dir)),
                "size_bytes": stat.st_size,
                "sha256": digest.hexdigest(),
                "source": "synthetic_folder",
            })
        except (OSError, ValueError):
            continue
    return results


def _case_for(applicant_id: str, cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    matching = [c for c in cases if c.get("applicant_id") == applicant_id]
    matching.sort(key=lambda c: str(c.get("updated_at") or ""), reverse=True)
    return matching[0] if matching else None


def _is_completed(case: dict[str, Any] | None) -> bool:
    if not case:
        return False
    values = {
        str(case.get("status") or "").strip().lower(),
        str(case.get("final_status") or "").strip().lower(),
        str(case.get("workflow_status") or "").strip().lower(),
    }
    return bool(values & {"completed", "closed", "issued", "declined", "rejected_final"})


def _form_from_records(applicant: dict[str, Any], case: dict[str, Any] | None) -> dict[str, Any]:
    profile = applicant.get("applicant_profile") or {}
    state = case or {}
    submission = state.get("submission") or {}
    dob = _iso_dob(profile.get("date_of_birth") or profile.get("dob"))

    conditions: list[dict[str, Any]] = []
    for item in profile.get("medical_conditions") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("condition") or item.get("name") or "").strip()
        if not label:
            continue
        mapped = intake.lookup_condition(label)
        conditions.append({
            "key": mapped.get("key"), "label": mapped.get("label") or label,
            "answers": {
                "since": str(item.get("year_diagnosed") or ""),
                "status": str(item.get("status") or ""),
            },
        })

    medications = profile.get("medications") or []
    for condition in conditions:
        label = condition["label"].casefold()
        names = [str(m.get("name") or m.get("medication") or "") for m in medications
                 if isinstance(m, dict) and (not m.get("indication") or str(m.get("indication")).casefold() in label)]
        if names:
            condition["answers"]["medicines"] = "; ".join(n for n in names if n)

    hospitals = profile.get("hospitalizations") or []
    claims = profile.get("claims") or []
    policy = profile.get("existing_policy") or {}
    bmi = profile.get("bmi")
    height = profile.get("height_cm")
    weight = profile.get("weight_kg")

    form = {
        "name": profile.get("name") or applicant.get("applicant_id", ""),
        "dob": dob,
        "sex": profile.get("sex") or profile.get("gender") or "",
        "product": submission.get("product") or "MedShield Comprehensive",
        "policy_type": submission.get("policy_type") or "Individual",
        "term_years": submission.get("term_years") or 1,
        "sum_insured": submission.get("sum_insured") or policy.get("sum_insured") or 0,
        "smoker": _yes(profile.get("smoker")),
        "alcohol_consumption": profile.get("alcohol_consumption") or profile.get("alcohol_use") or "",
        "hospital_stay": "yes" if hospitals else "no",
        "hospital_details": "; ".join(str(h.get("details") or h.get("reason") or "") for h in hospitals if isinstance(h, dict)),
        "had_claims": "yes" if claims else "no",
        "claims_details": "; ".join(str(c.get("details") or c.get("claim_id") or "") for c in claims if isinstance(c, dict)),
        "claim_count": len(claims),
        "has_other_insurance": "yes" if policy and any(v not in (None, "", 0) for v in policy.values()) else "no",
        "previous_insurer": policy.get("insurer") or "",
        "previous_policy_number": policy.get("policy_id") or "",
        "previous_policy_cover": policy.get("sum_insured") or "",
        "previous_policy_expiry": policy.get("expiry_date") or "",
        "height_cm": height or "",
        "weight_kg": weight or "",
        "occupation": profile.get("occupation") or "",
        "email": profile.get("email") or "",
        "phone": profile.get("phone") or "",
        "address": profile.get("address") or "",
        "family_members": profile.get("family_members") or [],
        "conditions": conditions,
        "consent": False,
    }
    # Keep sample data complete where source fields exist, but never fabricate
    # applicant consent. The applicant must confirm before submission.
    if bmi and not (height and weight):
        form["bmi"] = bmi
    return form


def _merge_submission_pdf(form: dict[str, Any], applicant_id: str, root: Path | None = None) -> dict[str, Any]:
    """Use the case's underwriting submission PDF as the sample's primary source."""
    applicant_root = (root or settings.synthetic_data_directory / "applicants") / applicant_id
    if not applicant_root.is_dir():
        return form
    pdfs = sorted(applicant_root.rglob("*.pdf"))
    if not pdfs:
        return form
    try:
        from app.rag.structured import build_applicant_facts
        facts = build_applicant_facts(pdfs)
        submission = facts.get("submission") or {}
        if not submission:
            return form

        # Submission fields take precedence over stale/default case values.
        if submission.get("name"):
            form["name"] = submission["name"]
        if submission.get("dob"):
            form["dob"] = submission["dob"]
        if submission.get("product"):
            form["product"] = submission["product"]
        if submission.get("policy_type"):
            form["policy_type"] = submission["policy_type"]
        if submission.get("sum_insured"):
            form["sum_insured"] = int(submission["sum_insured"])
        if submission.get("deductible") is not None:
            form["deductible"] = int(submission["deductible"])
        if submission.get("term_years"):
            form["term_years"] = int(submission["term_years"])
        if submission.get("remarks"):
            form["remarks"] = submission["remarks"]

        conditions = []
        for item in submission.get("conditions") or []:
            label = str(item.get("condition") or "").strip()
            if not label:
                continue
            mapped = intake.lookup_condition(label)
            conditions.append({
                "key": mapped.get("key"),
                "label": mapped.get("label") or label,
                "answers": {
                    "since": str(item.get("year_diagnosed") or ""),
                    "status": str(item.get("status") or ""),
                },
            })
        if conditions:
            form["conditions"] = conditions

        meds = submission.get("medications") or facts.get("medications") or []
        for condition in form.get("conditions", []):
            related = [
                str(m.get("name") or "") for m in meds
                if isinstance(m, dict) and (
                    not m.get("indication")
                    or str(m.get("indication")).casefold() in str(condition.get("label", "")).casefold()
                )
            ]
            if related:
                condition.setdefault("answers", {})["medicines"] = "; ".join(x for x in related if x)

        hospitals = submission.get("hospitalizations") or []
        form["hospital_stay"] = "yes" if hospitals else "no"
        form["hospital_details"] = "; ".join(
            str(h.get("details") or h.get("reason") or "") for h in hospitals if isinstance(h, dict)
        )

        insurance = submission.get("insurance") or []
        if insurance:
            policy = insurance[0]
            form["has_other_insurance"] = "yes"
            form["previous_insurer"] = policy.get("insurer") or form.get("previous_insurer", "")
            form["previous_policy_number"] = policy.get("policy_id") or form.get("previous_policy_number", "")
            form["previous_policy_cover"] = policy.get("sum_insured") or form.get("previous_policy_cover", "")
            form["previous_policy_status"] = policy.get("status") or ""
        questionnaire = submission.get("questionnaire") or []
        for row in questionnaire:
            question = str(row.get("question") or "").casefold()
            answer = str(row.get("answer") or "").casefold()
            if "claim" in question and answer:
                form["had_claims"] = "yes" if answer in {"yes", "true"} else "no"
        if not form.get("had_claims"):
            declared = " ".join(str(x.get("claims_declared") or "") for x in insurance if isinstance(x, dict)).casefold()
            form["had_claims"] = "no" if "no claim" in declared or not submission.get("claim_ids") else "yes"

        # Medical reports can supplement profile fields, but do not overwrite
        # an applicant-provided contact detail with an inferred value.
        if facts.get("smoking"):
            form["smoker"] = "yes" if facts["smoking"] == "smoker" else "no"
        if facts.get("alcohol"):
            form["alcohol_consumption"] = facts["alcohol"].title()
        return form
    except Exception:
        # Keep sample loading resilient; diagnostics remain available in the backend.
        return form


def listing(applicants: list[dict[str, Any]] | None = None,
            cases: list[dict[str, Any]] | None = None,
            root: Path | None = None) -> list[dict[str, Any]]:
    """All SQL applicants except those whose latest case is terminal."""
    if applicants is None:
        from app.store.state_store import state_store
        applicants = state_store.list_applicants(limit=1000)
    if cases is None:
        from app.store.state_store import state_store
        cases = state_store.list_cases(limit=1000)
    output = []
    for applicant in applicants:
        applicant_id = str(applicant.get("applicant_id") or "")
        if not applicant_id:
            continue
        applicant_cases = [c for c in cases if c.get("applicant_id") == applicant_id]
        case = _case_for(applicant_id, cases)
        # Once any underwriting run reaches a terminal outcome, keep this
        # applicant out of the demo autofill list. Historical records remain.
        if any(_is_completed(item) for item in applicant_cases):
            continue
        docs = discover_documents(applicant_id, root)
        profile = applicant.get("applicant_profile") or {}
        output.append({
            "id": applicant_id,
            "label": f"{profile.get('name') or applicant_id} · {applicant_id}",
            "description": f"{len(profile.get('medical_conditions') or [])} declared condition(s) · {len(docs)} supporting document(s)",
            "has_documents": bool(docs),
            "documents_expected": bool(docs),
            "document_count": len(docs),
            "source": applicant.get("source") or "synthetic",
        })
    return output


def get(applicant_id: str, applicant: dict[str, Any] | None = None,
        case: dict[str, Any] | None = None, root: Path | None = None) -> dict[str, Any] | None:
    """Build a live form and supporting-document inventory from SQL + folders."""
    if applicant is None:
        from app.store.state_store import state_store
        applicant = state_store.get_applicant(applicant_id)
    if not applicant:
        return None
    docs = discover_documents(applicant_id, root)
    form = _form_from_records(applicant, case)
    form = _merge_submission_pdf(form, applicant_id, root)
    return {
        "id": applicant_id,
        "label": f"{form.get('name') or applicant_id} · {applicant_id}",
        "form": form,
        "documents": docs,
    }
