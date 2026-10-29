from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from app.config import settings
from app.store.state_store import state_store


APPLICANTS_DIR = settings.synthetic_data_directory / "applicants"


# ============================================================
# PDF HELPERS
# ============================================================

def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))

    pages: list[str] = []

    for page in reader.pages:
        text = page.extract_text() or ""

        if text.strip():
            pages.append(text)

    return "\n".join(pages)


def find_submission_pdf(
    applicant_dir: Path,
) -> Path | None:
    underwriting_dir = applicant_dir / "underwriting"

    if not underwriting_dir.exists():
        return None

    files = sorted(underwriting_dir.glob("*.pdf"))

    return files[0] if files else None


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def extract_between(
    text: str,
    start_pattern: str,
    end_pattern: str,
) -> str:
    match = re.search(
        rf"{start_pattern}(.*?){end_pattern}",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return ""

    return match.group(1).strip()


def extract_single_line(
    text: str,
    pattern: str,
) -> str:
    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    if not match:
        return ""

    return clean_text(match.group(1))


# ============================================================
# APPLICANT PROFILE
# ============================================================

def extract_applicant_profile(
    text: str,
    applicant_id: str,
) -> dict[str, Any]:

    name = extract_single_line(
        text,
        r"Applicant\s*\n([^\n]+)",
    )

    dob = ""
    age: int | None = None

    dob_age_match = re.search(
        r"Date of birth / age\s*\n"
        r"([^\n]+?)\s*/\s*(\d+)\s*years",
        text,
        flags=re.IGNORECASE,
    )

    if dob_age_match:
        dob = clean_text(dob_age_match.group(1))
        age = int(dob_age_match.group(2))

    if not name:
        name = applicant_id

    profile: dict[str, Any] = {
        "applicant_id": applicant_id,
        "name": name,
        "date_of_birth": dob,
        "age": age,
        "source": "synthetic_dataset",
    }

    # Optional lifestyle fields; only set when the document states them.
    smoking = extract_single_line(text, r"Smoking status\s*\n([^\n]+)")
    if smoking:
        profile["smoker"] = not re.search(
            r"\b(non[- ]?smoker|never|no|former|quit)\b",
            smoking,
            flags=re.IGNORECASE,
        )

    bmi_match = re.search(r"\bBMI\b\s*\n?\s*(\d{2}(?:\.\d+)?)", text)
    if bmi_match:
        profile["bmi"] = float(bmi_match.group(1))

    return profile


# ============================================================
# CONDITIONS
# ============================================================

def extract_conditions(
    text: str,
) -> list[dict[str, Any]]:

    section = extract_between(
        text,
        r"3\.\s*Declared Medical Conditions",
        r"4\.\s*Declared Medications",
    )

    if not section:
        return []

    conditions: list[dict[str, Any]] = []

    matches = re.findall(
        r"\n\s*(.+?)\s*\n\s*"
        r"(20\d{2})\s*\n\s*"
        r"(.+?)(?=\n\s*(?:.+?)\s*\n\s*20\d{2}\s*\n|\Z)",
        section,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for condition, year, status in matches:
        condition = clean_text(condition)
        status = clean_text(status)

        if not condition:
            continue

        conditions.append(
            {
                "condition": condition,
                "year_diagnosed": int(year),
                "status": status,
            }
        )

    return conditions


# ============================================================
# MEDICATIONS
# ============================================================

def _looks_like_medication_name(value: str) -> bool:
    """
    Accept medication-like names while rejecting common
    PDF extraction artifacts and clinical indication words.
    """

    value = clean_text(value)

    if not value:
        return False

    normalized = value.lower()

    rejected_values = {
        "medication",
        "medications",
        "dose",
        "dose and frequency",
        "frequency",
        "indication",
        "duration",
        "none",
        "nil",
        "no medications",
        "not applicable",
        "intermittent",
        "ongoing",
        "current",
        "history",
        "gerd",
        "hypertension",
        "diabetes",
        "asthma",
        "arthritis",
        "migraine",
        "pain",
        "infection",
    }

    if normalized in rejected_values:
        return False

    # Medication names in the synthetic dataset are expected
    # to contain alphabetic characters and normally start with
    # a capital letter.
    if not re.match(
        r"^[A-Z][A-Za-z0-9-]*(?:\s+[A-Za-z0-9-]+)*$",
        value,
    ):
        return False

    # Reject obvious section/header text.
    header_words = {
        "declared",
        "medical",
        "conditions",
        "hospitalizations",
        "insurance",
        "policy",
        "claims",
        "applicant",
        "submission",
        "details",
    }

    if normalized in header_words:
        return False

    return True


def _is_medication_detail(value: str) -> bool:
    value = clean_text(value)

    if not value:
        return False

    normalized = value.lower()

    if normalized in {
        "indication",
        "duration",
        "dose and frequency",
    }:
        return False

    # Typical dose/frequency information.
    if re.search(
        r"\b\d+\s*(mg|mcg|g|ml|tablet|tablets|capsule|capsules)\b",
        normalized,
    ):
        return True

    if re.search(
        r"\b(once|twice|daily|weekly|monthly|bd|od|tds|bid|tid|qid)\b",
        normalized,
    ):
        return True

    return False


def extract_medications(
    text: str,
) -> list[dict[str, Any]]:

    section = extract_between(
        text,
        r"4\.\s*Declared Medications",
        r"5\.\s*Declared Hospitalizations",
    )

    if not section:
        return []

    lines = [
        clean_text(line)
        for line in section.splitlines()
        if clean_text(line)
    ]

    medications: list[dict[str, Any]] = []

    # Remove table headings.
    skip_values = {
        "medication",
        "dose and frequency",
        "indication",
        "duration",
        "name",
        "details",
    }

    index = 0

    while index < len(lines):

        line = lines[index]

        if line.lower() in skip_values:
            index += 1
            continue

        if not _looks_like_medication_name(line):
            index += 1
            continue

        medication: dict[str, Any] = {
            "name": line,
        }

        # The next one or two lines may contain medication details.
        details: list[str] = []

        for offset in (1, 2):
            next_index = index + offset

            if next_index >= len(lines):
                break

            candidate = lines[next_index]

            if _looks_like_medication_name(candidate):
                break

            if _is_medication_detail(candidate):
                details.append(candidate)

        if details:
            medication["details"] = " ".join(details)

        medications.append(medication)

        index += 1

    # Remove duplicates.
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for medication in medications:
        name = clean_text(medication.get("name"))

        key = name.lower()

        if not key or key in seen:
            continue

        seen.add(key)

        result.append(medication)

    return result


# ============================================================
# HOSPITALIZATIONS
# ============================================================

def extract_hospitalizations(
    text: str,
) -> list[dict[str, Any]]:

    section = extract_between(
        text,
        r"5\.\s*Declared Hospitalizations",
        r"6\.\s*Existing Insurance",
    )

    if not section:
        return []

    events: list[dict[str, Any]] = []

    date_pattern = (
        r"(\d{2}-[A-Za-z]{3}-\d{4}"
        r"(?:\s+to\s+\d{2}-[A-Za-z]{3}-\d{4})?"
        r"(?:\s+\(day-care\))?)"
    )

    dates = list(
        re.finditer(
            date_pattern,
            section,
            flags=re.IGNORECASE,
        )
    )

    for index, match in enumerate(dates):
        start = match.start()

        end = (
            dates[index + 1].start()
            if index + 1 < len(dates)
            else len(section)
        )

        block = section[start:end]
        block = clean_text(block)

        if not block:
            continue

        events.append(
            {
                "details": block,
            }
        )

    return events


# ============================================================
# CLAIMS
# ============================================================

def extract_claims(
    text: str,
) -> list[dict[str, Any]]:

    claim_ids = re.findall(
        r"CLM-\d{5}",
        text,
        flags=re.IGNORECASE,
    )

    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for claim_id in claim_ids:
        claim_id = claim_id.upper()

        if claim_id in seen:
            continue

        seen.add(claim_id)

        result.append(
            {
                "claim_id": claim_id,
                "status": "historical",
            }
        )

    return result


# ============================================================
# EXISTING POLICY
# ============================================================

def extract_existing_policy(
    text: str,
) -> dict[str, Any]:

    policy_match = re.search(
        r"\bPOL-\d{3}\b",
        text,
        flags=re.IGNORECASE,
    )

    policy_id = (
        policy_match.group(0).upper()
        if policy_match
        else ""
    )

    return {
        "policy_id": policy_id,
        "status": "active" if policy_id else "",
    }


# ============================================================
# REQUESTED COVER
# ============================================================

def extract_submission(
    text: str,
) -> dict[str, Any]:

    product = extract_single_line(
        text,
        r"Requested product\s*\n([^\n]+)",
    )

    policy_type = extract_single_line(
        text,
        r"Policy type\s*\n([^\n]+)",
    )

    sum_insured_text = extract_single_line(
        text,
        r"Requested sum insured\s*\(INR\)\s*\n([^\n]+)",
    )

    term_text = extract_single_line(
        text,
        r"Policy term\s*\n([^\n]+)",
    )

    requested_start_date = extract_single_line(
        text,
        r"Requested start date\s*\n([^\n]+)",
    )

    sum_insured: int | None = None

    digits = re.sub(
        r"[^\d]",
        "",
        sum_insured_text,
    )

    if digits:
        sum_insured = int(digits)

    term_match = re.search(
        r"(\d+)\s*year",
        term_text,
        flags=re.IGNORECASE,
    )

    term_years = (
        int(term_match.group(1))
        if term_match
        else 1
    )

    submission: dict[str, Any] = {
        "product": product,
        "policy_type": policy_type,
        "sum_insured": sum_insured,
        "term_years": term_years,
        "requested_start_date": requested_start_date,
        "jurisdiction": "India",
        "insurer": "DEMO_INSURER",
    }

    # Optional free-text note from the submitter (screened by guardrails).
    notes = extract_between(
        text,
        r"Underwriting note",
        r"(?:\n\d+\.\s|\Z)",
    )
    if notes:
        submission["notes"] = clean_text(notes)[:1000]

    return submission


# ============================================================
# PROFILE VALIDATION
# ============================================================

def validate_profile(
    profile: dict[str, Any],
) -> dict[str, Any]:

    conditions = profile.get(
        "medical_conditions",
        [],
    )

    medications = profile.get(
        "medications",
        [],
    )

    hospitalizations = profile.get(
        "hospitalizations",
        [],
    )

    claims = profile.get(
        "claims",
        [],
    )

    if not isinstance(conditions, list):
        profile["medical_conditions"] = []

    if not isinstance(medications, list):
        profile["medications"] = []

    if not isinstance(hospitalizations, list):
        profile["hospitalizations"] = []

    if not isinstance(claims, list):
        profile["claims"] = []

    # Remove invalid medication records.
    valid_medications: list[dict[str, Any]] = []

    for medication in profile["medications"]:
        if not isinstance(medication, dict):
            continue

        name = clean_text(
            medication.get("name")
        )

        if not _looks_like_medication_name(name):
            print(
                f"[WARNING] Invalid medication removed: "
                f"{name!r}"
            )
            continue

        cleaned = {
            "name": name,
        }

        details = clean_text(
            medication.get("details")
        )

        if details:
            cleaned["details"] = details

        valid_medications.append(cleaned)

    profile["medications"] = valid_medications

    # Remove duplicate conditions.
    valid_conditions: list[dict[str, Any]] = []
    seen_conditions: set[str] = set()

    for condition in profile["medical_conditions"]:
        if not isinstance(condition, dict):
            continue

        name = clean_text(
            condition.get("condition")
        )

        if not name:
            continue

        key = name.lower()

        if key in seen_conditions:
            continue

        seen_conditions.add(key)

        valid_conditions.append(
            {
                "condition": name,
                "year_diagnosed": condition.get(
                    "year_diagnosed"
                ),
                "status": clean_text(
                    condition.get("status")
                ),
            }
        )

    profile["medical_conditions"] = valid_conditions

    return profile


# ============================================================
# BUILD PROFILE
# ============================================================

def build_profile(
    applicant_id: str,
    text: str,
) -> dict[str, Any]:

    profile = extract_applicant_profile(
        text,
        applicant_id,
    )

    profile.update(
        {
            "medical_conditions": extract_conditions(text),
            "medications": extract_medications(text),
            "hospitalizations": extract_hospitalizations(text),
            "claims": extract_claims(text),
            "existing_policy": extract_existing_policy(text),
        }
    )

    return validate_profile(profile)


# ============================================================
# CASE STATE
# ============================================================

def build_case_state(
    case_id: str,
    applicant_id: str,
    profile: dict[str, Any],
    submission: dict[str, Any],
    existing_state: dict[str, Any] | None = None,
) -> dict[str, Any]:

    state = dict(existing_state or {})

    state.update(
        {
            "case_id": case_id,
            "applicant_id": applicant_id,
            "applicant_profile": profile,
            "submission": submission,
        }
    )

    state.setdefault("status", "draft")
    state.setdefault("final_decision", "")
    state.setdefault("final_recommendation", "")
    state.setdefault("overall_risk_score", None)
    state.setdefault("medical_risk_score", None)
    state.setdefault("claims_risk_score", None)
    state.setdefault("coverage_gap_score", None)
    state.setdefault("workflow_trace", [])
    state.setdefault("audit_trail", [])
    state.setdefault("errors", [])

    return state


# ============================================================
# SEED ONE APPLICANT
# ============================================================

def seed_applicant(
    applicant_dir: Path,
) -> bool:

    applicant_id = applicant_dir.name

    submission_pdf = find_submission_pdf(
        applicant_dir
    )

    if not submission_pdf:
        print(
            f"[SKIP] {applicant_id}: "
            "submission PDF not found."
        )
        return False

    text = extract_pdf_text(
        submission_pdf
    )

    if not text.strip():
        print(
            f"[SKIP] {applicant_id}: "
            "submission PDF contains no text."
        )
        return False

    profile = build_profile(
        applicant_id,
        text,
    )

    submission = extract_submission(
        text
    )

    existing = state_store.get_applicant(
        applicant_id
    )

    if existing:
        state_store.update_applicant(
            applicant_id=applicant_id,
            applicant_profile=profile,
        )

        print(
            f"[UPDATED] {applicant_id} | "
            f"{profile.get('name', applicant_id)}"
        )

    else:
        state_store.create_applicant(
            applicant_id=applicant_id,
            applicant_profile=profile,
            source="synthetic_dataset",
        )

        print(
            f"[CREATED] {applicant_id} | "
            f"{profile.get('name', applicant_id)}"
        )

    case_id = f"UW-{applicant_id.replace('APP-', '')}"

    existing_case = state_store.get_case(
        case_id
    )

    existing_state = (
        existing_case.get("state", {})
        if existing_case
        else None
    )

    state = build_case_state(
        case_id=case_id,
        applicant_id=applicant_id,
        profile=profile,
        submission=submission,
        existing_state=existing_state,
    )

    if existing_case:
        state_store.save_case(
            case_id=case_id,
            state=state,
            status=existing_case.get(
                "status",
                "draft",
            ),
        )

        print(
            f"  [CASE UPDATED] {case_id}"
        )

    else:
        state_store.create_case(
            case_id=case_id,
            applicant_id=applicant_id,
            state=state,
            status="draft",
        )

        print(
            f"  [CASE CREATED] {case_id}"
        )

    print(
        f"  Name: {profile.get('name')}"
    )
    print(
        f"  Age: {profile.get('age')}"
    )
    print(
        f"  Conditions: "
        f"{len(profile.get('medical_conditions', []))}"
    )
    print(
        f"  Medications: "
        f"{len(profile.get('medications', []))}"
    )
    print(
        f"  Hospitalizations: "
        f"{len(profile.get('hospitalizations', []))}"
    )
    print(
        f"  Claims: "
        f"{len(profile.get('claims', []))}"
    )

    return True


# ============================================================
# MAIN
# ============================================================

def seed() -> None:

    print("=" * 70)
    print(
        "MedUnderwrite AI - Synthetic Database Seeder"
    )
    print("=" * 70)

    if not APPLICANTS_DIR.exists():
        raise FileNotFoundError(
            f"Applicant directory not found: "
            f"{APPLICANTS_DIR}"
        )

    applicant_dirs = sorted(
        path
        for path in APPLICANTS_DIR.iterdir()
        if path.is_dir()
        and path.name.startswith("APP-")
    )

    print(
        f"\nFound {len(applicant_dirs)} "
        "synthetic applicant directories.\n"
    )

    success = 0
    skipped = 0

    for applicant_dir in applicant_dirs:

        try:
            if seed_applicant(
                applicant_dir
            ):
                success += 1
            else:
                skipped += 1

        except Exception as exc:
            skipped += 1

            print(
                f"[ERROR] "
                f"{applicant_dir.name}: {exc}"
            )

        print("-" * 70)

    print("\nCompleted.")

    print(
        f"Applicants processed: {success}"
    )

    print(
        f"Skipped/failed: {skipped}"
    )

    print("=" * 70)


if __name__ == "__main__":
    seed()