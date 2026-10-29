"""
Medical severity assessment: serious, moderate, routine or indeterminate.

A condition is judged on what it is (a stent or NSTEMI is serious), how well
it is controlled (BP readings, HbA1c, eGFR), whether complications are
documented, and whether the evidence is sufficient to say. Declared or not,
the assessment feeds scoring; an *undeclared* condition only forces human
review when it is serious (or when the missing information is material).

Pure Python, no I/O.
"""
from __future__ import annotations

import re
from typing import Any

from app.services.medical_groups import group_label

TIERS = ("serious", "moderate", "routine", "indeterminate")

_NEGATION = re.compile(
    r"\b(no|not|without|denies|denied|negative for|nil|absence of|free of|family history|"
    r"father|mother|parents?|sister|brother)\b[^.;\n]{0,45}$",
    re.IGNORECASE,
)

_CARDIAC_SERIOUS = re.compile(
    r"nstemi|\bstemi\b|myocardial infarction|heart attack|\bstents?\b|angioplasty|\bpci\b|"
    r"\bcabg\b|bypass (surgery|graft)|heart failure|cardiomyopath|ischaemic heart|"
    r"ischemic heart|coronary artery disease|\bcad\b|acute coronary|unstable angina",
    re.IGNORECASE,
)
_CARDIAC_ICD = re.compile(r"^(I21|I22|I24|I25|I50|Z95|Z98\.61)", re.IGNORECASE)

_COMPLICATIONS = {
    "diabetes": r"retinopathy|nephropathy|neuropathy|diabetic foot|foot ulcer|microalbuminuria|"
                r"albuminuria|proteinuria|gangrene|amputation|ketoacidosis",
    "hypertension": r"left ventricular hypertrophy|\blvh\b|hypertensive (retinopathy|nephropathy|heart)|"
                    r"end[- ]organ damage",
}

_ANTIHYPERTENSIVES = re.compile(
    r"amlodipine|nifedipine|telmisartan|losartan|olmesartan|valsartan|irbesartan|enalapril|"
    r"ramipril|lisinopril|perindopril|metoprolol|atenolol|bisoprolol|carvedilol|nebivolol|"
    r"hydrochlorothiazide|chlorthalidone|indapamide|spironolactone|furosemide|clonidine|prazosin",
    re.IGNORECASE,
)

_LAB_PATTERNS = {
    "hba1c": r"hba1c|glycated h|glycosylated h|\ba1c\b",
    "egfr": r"\begfr\b|estimated gfr|glomerular filtration",
    "creatinine": r"creatinine(?!.*ratio)",
    "uacr": r"albumin[- /]*creatinine|\buacr\b|\bacr\b|microalbumin",
    "fasting_glucose": r"fasting (plasma )?glucose|fasting blood (sugar|glucose)|\bfbs\b|\bfpg\b",
}


def _affirmed(text: str, pattern: re.Pattern[str] | str) -> bool:
    """True if the pattern appears and is not negated / about a relative."""
    regex = re.compile(pattern, re.IGNORECASE) if isinstance(pattern, str) else pattern
    for match in regex.finditer(text or ""):
        before = text[max(0, match.start() - 60): match.start()]
        if not _NEGATION.search(before):
            return True
    return False


def parse_bp(value: Any) -> tuple[int, int] | None:
    match = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", str(value or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def lab_value(labs: list[dict[str, Any]], key: str) -> float | None:
    """Latest numeric value of a lab by canonical name (hba1c, egfr, ...)."""
    pattern = re.compile(_LAB_PATTERNS[key], re.IGNORECASE)
    found = [
        lab for lab in labs or []
        if lab.get("value") is not None and pattern.search(str(lab.get("name", "")))
    ]
    if not found:
        return None
    found.sort(key=lambda lab: lab.get("document_date") or "", reverse=True)
    return float(found[0]["value"])


def _entry(
    group: str,
    tier: str,
    control: str,
    reasons: list[str],
    *,
    complications: list[str] | None = None,
    missing: list[str] | None = None,
    reassuring: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "group": group,
        "label": group_label(group),
        "tier": tier,
        "control": control,
        "reasons": reasons,
        "complications": complications or [],
        "missing": missing or [],
        "reassuring": reassuring or [],
    }


def _complications(group: str, text: str) -> list[str]:
    pattern = _COMPLICATIONS.get(group)
    if not pattern:
        return []
    found = []
    for match in re.finditer(pattern, text or "", re.IGNORECASE):
        before = text[max(0, match.start() - 60): match.start()]
        if not _NEGATION.search(before):
            found.append(match.group().lower())
    return list(dict.fromkeys(found))


def _reassuring_labs(labs: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    glucose = lab_value(labs, "fasting_glucose")
    if glucose is not None and glucose < 100:
        notes.append(f"fasting glucose {glucose:g} (normal)")
    creatinine = lab_value(labs, "creatinine")
    if creatinine is not None and creatinine <= 1.2:
        notes.append(f"creatinine {creatinine:g} (normal)")
    egfr = lab_value(labs, "egfr")
    if egfr is not None and egfr >= 90:
        notes.append(f"eGFR {egfr:g} (normal)")
    uacr = lab_value(labs, "uacr")
    if uacr is not None and uacr < 30:
        notes.append(f"urine albumin-creatinine ratio {uacr:g} (normal)")
    return notes


def assess_group(
    group: str,
    *,
    text: str,
    icd_codes: list[str] | None = None,
    vitals: dict[str, Any] | None = None,
    labs: list[dict[str, Any]] | None = None,
    medications: list[Any] | None = None,
    onset_known: bool = False,
    bmi: float | None = None,
) -> dict[str, Any]:
    """Severity of one condition group from the evidence available for it."""
    vitals = vitals or {}
    labs = labs or []
    icd_codes = icd_codes or []
    med_text = " ".join(
        str(m.get("name", m)) + " " + str(m.get("details", "")) if isinstance(m, dict) else str(m)
        for m in medications or []
    )
    egfr = lab_value(labs, "egfr")
    uacr = lab_value(labs, "uacr")

    if group == "cardiac":
        event = _affirmed(text, _CARDIAC_SERIOUS) or any(_CARDIAC_ICD.match(c) for c in icd_codes)
        if event:
            return _entry("cardiac", "serious", "unknown",
                          ["documented coronary event, stent / revascularisation or established heart disease"])
        return _entry("cardiac", "moderate", "unknown", ["cardiac condition without a documented event"])

    if group in {"cancer", "cerebrovascular", "hiv"}:
        return _entry(group, "serious", "unknown", [f"{group_label(group)} is always treated as serious"])

    if group == "renal":
        stage = re.search(r"stage\s*([3-5])|\bn18\.[3-9]|dialysis|end[- ]stage", text, re.IGNORECASE) or any(
            re.match(r"N18\.[3-9]|N17", c, re.IGNORECASE) for c in icd_codes
        )
        if stage or (egfr is not None and egfr < 60):
            return _entry("renal", "serious", "reduced", ["CKD stage 3 or worse / eGFR below 60"])
        if egfr is not None:
            return _entry("renal", "moderate", "preserved", [f"eGFR {egfr:g}"], reassuring=_reassuring_labs(labs))
        return _entry("renal", "indeterminate", "unknown", ["no eGFR / creatinine available"],
                      missing=["eGFR / creatinine"])

    if group == "liver":
        if _affirmed(text, r"cirrhosis|decompensat|hepatic failure|varices|ascites") or any(
            c.upper().startswith("K74") for c in icd_codes
        ):
            return _entry("liver", "serious", "unknown", ["cirrhosis or decompensated liver disease"])
        return _entry("liver", "moderate", "unknown", ["liver condition without documented cirrhosis"])

    if group == "respiratory":
        if _affirmed(text, r"severe|home oxygen|ventilat|respiratory failure|admission for exacerbation"):
            return _entry("respiratory", "serious", "poor", ["severe chronic respiratory disease"])
        if _affirmed(text, r"\bmild\b|well[- ]controlled|intermittent|seasonal"):
            return _entry("respiratory", "routine", "controlled", ["mild / controlled respiratory condition"])
        return _entry("respiratory", "moderate", "unknown", ["respiratory condition, severity not stated"])

    if group == "diabetes":
        comps = _complications("diabetes", text)
        if egfr is not None and egfr < 60:
            comps.append("reduced eGFR")
        if uacr is not None and uacr >= 30:
            comps.append("albuminuria")
        hba1c = lab_value(labs, "hba1c")
        insulin = bool(re.search(r"insulin|glargine|lispro|aspart", med_text, re.IGNORECASE))
        reassuring = _reassuring_labs(labs)
        missing: list[str] = []
        if hba1c is None:
            missing.append("HbA1c")
        if not onset_known and not re.search(r"since\s+\d{4}|diagnosed (in|on)\s+\d|for\s+\d+\s+years", text, re.IGNORECASE):
            missing.append("diabetes duration")
        if not comps and not re.search(
            r"no (known )?(retinopathy|nephropathy|neuropathy|complication)|complication[s]? (nil|none|absent)",
            text, re.IGNORECASE,
        ):
            missing.append("complication history")
        if comps:
            return _entry("diabetes", "serious", "unknown", ["documented diabetic complication: " + ", ".join(comps)],
                          complications=comps, missing=missing, reassuring=reassuring)
        if hba1c is not None:
            if hba1c < 7.5:
                tier, control = ("routine" if not insulin else "moderate"), "controlled"
            elif hba1c <= 9:
                tier, control = "moderate", "fair"
            else:
                tier, control = "serious", "uncontrolled"
            return _entry("diabetes", tier, control, [f"HbA1c {hba1c:g}"], missing=missing, reassuring=reassuring)
        return _entry(
            "diabetes", "indeterminate", "unknown",
            ["diabetes present; control cannot be judged without HbA1c" +
             (" (renal and glucose results are reassuring but do not show it is controlled or absent)" if reassuring else "")],
            missing=missing, reassuring=reassuring,
        )

    if group == "hypertension":
        bp = parse_bp(vitals.get("blood_pressure"))
        comps = _complications("hypertension", text)
        if egfr is not None and egfr < 60:
            comps.append("reduced eGFR")
        agents = len(set(m.lower() for m in _ANTIHYPERTENSIVES.findall(med_text)))
        if comps:
            return _entry("hypertension", "serious", "unknown", ["hypertension with complications: " + ", ".join(comps)],
                          complications=comps)
        if bp is None:
            return _entry("hypertension", "indeterminate", "unknown", ["no recent blood pressure reading"],
                          missing=["recent blood pressure readings"])
        sys_bp, dia_bp = bp
        if sys_bp >= 160 or dia_bp >= 100:
            return _entry("hypertension", "serious", "uncontrolled", [f"BP {sys_bp}/{dia_bp}"])
        if sys_bp >= 140 or dia_bp >= 90 or agents >= 3:
            return _entry("hypertension", "moderate", "fair",
                          [f"BP {sys_bp}/{dia_bp}" + (f" on {agents} agents" if agents >= 3 else "")])
        return _entry("hypertension", "routine", "controlled", [f"BP {sys_bp}/{dia_bp}" +
                                                                (f" on treatment ({med_text.split()[0]})" if agents and med_text.split() else "")])

    if group == "thyroid":
        return _entry("thyroid", "routine", "unknown", ["thyroid disorder on replacement / stable"])

    if group == "neurological":
        if _affirmed(text, r"parkinson|multiple sclerosis|\bms\b|stroke"):
            return _entry("neurological", "serious", "unknown", ["progressive or serious neurological disease"])
        if _affirmed(text, r"migraine"):
            return _entry("neurological", "routine", "unknown", ["migraine"])
        return _entry("neurological", "moderate", "unknown", ["neurological condition"])

    if group in {"mental_health", "substance"}:
        if _affirmed(text, r"schizophren|bipolar|psychosis|suicid|hospitali[sz]|dependence"):
            return _entry(group, "serious", "unknown", ["serious mental-health or substance condition"])
        return _entry(group, "moderate", "unknown", ["mental-health or substance condition"])

    if group == "autoimmune":
        return _entry("autoimmune", "moderate", "unknown", ["autoimmune / rheumatological condition"])

    if group == "obesity" or (bmi is not None and bmi >= 35):
        return _entry("obesity", "moderate" if (bmi or 0) >= 35 else "routine", "unknown",
                      [f"BMI {bmi:g}" if bmi else "obesity"])

    return _entry(group, "routine", "unknown", ["common condition without markers of severity"])


def assess_conditions(
    *,
    groups: dict[str, dict[str, Any]],
    vitals: dict[str, Any] | None,
    labs: list[dict[str, Any]] | None,
    medications: list[Any] | None,
    age: float | None,
    sum_insured: float | None,
    age_threshold: int = 45,
    sum_insured_threshold: float = 1_000_000,
    bmi: float | None = None,
) -> list[dict[str, Any]]:
    """
    Assess every group present.

    `groups` maps group -> {"text": evidence text, "icd": [codes],
    "declared": bool, "onset_known": bool, "sources": [document ids]}.
    """
    material_context = bool(
        (age and age >= age_threshold) or (sum_insured and sum_insured >= sum_insured_threshold)
    )
    results = []
    for group, info in groups.items():
        entry = assess_group(
            group,
            text=info.get("text", ""),
            icd_codes=info.get("icd", []),
            vitals=vitals,
            labs=labs,
            medications=medications,
            onset_known=info.get("onset_known", False),
            bmi=bmi,
        )
        entry["declared"] = bool(info.get("declared"))
        entry["sources"] = info.get("sources", [])
        # Missing information only matters when the case is large enough.
        entry["material_missing"] = entry["missing"] if material_context else []
        results.append(entry)
    return results