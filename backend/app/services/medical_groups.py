"""
Condition groups: one vocabulary for declared conditions, documented
diagnoses (ICD-10-CM codes) and questionnaire answers.

Comparing *groups* instead of words is what lets "kidney stones" (declared)
match "renal colic" / N13.2 / Z87.442 (documented), while a documented
chronic kidney disease (N18) is still a different group.
"""
from __future__ import annotations

import re

# Groups whose absence from the declaration is material.
STRONG_GROUPS = {
    "diabetes",
    "thyroid",
    "hypertension",
    "cardiac",
    "cerebrovascular",
    "cancer",
    "renal",
    "liver",
    "respiratory",
    "autoimmune",
    "neurological",
    "mental_health",
    "substance",
    "hiv",
}

GROUP_LABELS = {
    "diabetes": "diabetes",
    "thyroid": "thyroid disorder",
    "hypertension": "hypertension",
    "cardiac": "heart disease",
    "cerebrovascular": "cerebrovascular disease",
    "cancer": "cancer",
    "renal": "chronic kidney disease",
    "urinary_calculi": "urinary calculi",
    "liver": "liver disease",
    "respiratory": "chronic respiratory disease",
    "autoimmune": "autoimmune / rheumatological disease",
    "neurological": "neurological disease",
    "mental_health": "mental health condition",
    "substance": "substance use disorder",
    "hiv": "HIV",
    "spine": "spine / disc disorder",
    "musculoskeletal": "joint / musculoskeletal disorder",
    "gi": "digestive disorder",
    "gallbladder": "gallbladder disease / gallstones",
    "hernia": "hernia",
    "eye": "eye disease (cataract)",
    "prostate": "prostate condition",
    "lipids": "dyslipidaemia",
    "obesity": "obesity",
    "other": "other condition",
}

# (inclusive ICD-10 3-character range, group), checked in order.
_ICD_RANGES: list[tuple[str, str, str]] = [
    ("E00", "E07", "thyroid"),
    ("E10", "E14", "diabetes"),
    ("E66", "E66", "obesity"),
    ("E78", "E78", "lipids"),
    ("I10", "I16", "hypertension"),
    ("I20", "I52", "cardiac"),
    ("I60", "I69", "cerebrovascular"),
    ("C00", "C97", "cancer"),
    ("D00", "D09", "cancer"),
    ("D37", "D48", "cancer"),
    ("N00", "N08", "renal"),
    ("N17", "N19", "renal"),
    ("N20", "N23", "urinary_calculi"),
    ("N13", "N13", "urinary_calculi"),
    ("K70", "K77", "liver"),
    ("K80", "K87", "gallbladder"),
    ("K40", "K46", "hernia"),
    ("H25", "H26", "eye"),
    ("N40", "N40", "prostate"),
    ("K21", "K31", "gi"),
    ("J40", "J47", "respiratory"),
    ("M05", "M14", "autoimmune"),
    ("M32", "M35", "autoimmune"),
    ("M45", "M45", "autoimmune"),
    ("M15", "M19", "musculoskeletal"),
    ("M40", "M54", "spine"),
    ("G20", "G26", "neurological"),
    ("G35", "G37", "neurological"),
    ("G40", "G41", "neurological"),
    ("F00", "F09", "mental_health"),
    ("F20", "F48", "mental_health"),
    ("F10", "F19", "substance"),
    ("B20", "B24", "hiv"),
]

# Personal-history codes that map to a group.
_HISTORY_CODES = {
    "Z87.442": "urinary_calculi",
    "Z87.4": "urinary_calculi",
    "Z85": "cancer",
    "Z95": "cardiac",
    "Z86.73": "cerebrovascular",
}

# (regex, group) for free text, most specific first.
_TEXT_PATTERNS: list[tuple[str, str]] = [
    (r"chronic kidney|ckd\b|renal failure|renal insufficiency|nephropath|nephritis|dialysis", "renal"),
    (r"kidney stone|urinary (tract )?calcul|calculus|calculi|lithotrips|ureter|renal colic|hydronephro|urolith", "urinary_calculi"),
    (r"diabet|hba1c|insulin|metformin", "diabetes"),
    (r"hypothyroid|hyperthyroid|thyroid", "thyroid"),
    (r"hypertens|high blood pressure", "hypertension"),
    (r"coronary|myocardial|angina|heart (disease|failure|attack)|cardiac|cardiomyopath|arrhythmi|atrial fibrill|stent", "cardiac"),
    (r"stroke|cerebrovascular|transient ischaemic|transient ischemic", "cerebrovascular"),
    (r"cancer|carcinoma|malignan|lymphoma|leukaemia|leukemia|tumou?r|oncolog", "cancer"),
    (r"cirrhosis|hepatitis|fatty liver|liver (disease|disorder)|hepatic", "liver"),
    (r"copd|chronic obstructive|asthma|bronchiectasis", "respiratory"),
    (r"rheumatoid|lupus|ankylosing|psoria|autoimmune|rheumatolog", "autoimmune"),
    (r"epilep|seizure|parkinson|multiple sclerosis|migraine", "neurological"),
    (r"depress|anxiety|bipolar|schizophren|psychiat|mental health", "mental_health"),
    (r"alcohol (use )?disorder|substance|drug (abuse|dependence)", "substance"),
    (r"\bhiv\b|\baids\b", "hiv"),
    (r"disc (herniation|prolapse|displacement)|radiculopath|lumbar|spondyl|sciatica|low back|back pain|spine|spinal", "spine"),
    (r"osteoarthritis|knee|joint|arthritis|osteopor", "musculoskeletal"),
    (r"gall(bladder|stone)|cholecyst", "gallbladder"),
    (r"\bhernia\b", "hernia"),
    (r"cataract", "eye"),
    (r"prostat|\bbph\b", "prostate"),
    (r"gerd|reflux|oesophag|esophag|gastritis|ulcer|irritable bowel|crohn|colitis", "gi"),
    (r"dyslipid|cholesterol|hyperlipid", "lipids"),
    (r"obes", "obesity"),
]

# Questionnaire question keywords -> groups an affirmative answer covers.
_QUESTION_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    (r"kidney|urinary|renal", ("renal", "urinary_calculi")),
    (r"liver", ("liver",)),
    (r"bone|joint|spine|rheumat|autoimmune", ("spine", "musculoskeletal", "autoimmune")),
    (r"digest|gallbladder|gerd|ulcer|bowel", ("gi", "liver")),
    (r"heart|cardiac|blood pressure|hypertens|circulat", ("cardiac", "hypertension", "cerebrovascular")),
    (r"diabet|thyroid|endocrine|hormon", ("diabetes", "thyroid")),
    (r"cancer|tumou?r|neoplas", ("cancer",)),
    (r"respirat|lung|asthma|chest", ("respiratory",)),
    (r"nerv|brain|epilep|neurolog", ("neurological", "cerebrovascular")),
    (r"mental|psychiatr|depress|anxiety", ("mental_health",)),
    (r"alcohol|drug|substance", ("substance",)),
    (r"hiv|aids", ("hiv",)),
]


def icd_group(code: str | None) -> str | None:
    if not code:
        return None
    code = str(code).strip().upper()
    for key, group in _HISTORY_CODES.items():
        if code.startswith(key):
            return group
    match = re.match(r"^([A-Z])(\d{2})", code)
    if not match:
        return None
    base = match.group(1) + match.group(2)
    for low, high, group in _ICD_RANGES:
        if low <= base <= high:
            return group
    return "other"


def text_group(text: str | None) -> str | None:
    lowered = str(text or "").lower()
    if not lowered.strip():
        return None
    for pattern, group in _TEXT_PATTERNS:
        if re.search(pattern, lowered):
            return group
    return None


def diagnosis_group(diagnosis: str | None, icd: str | None) -> str:
    """ICD code first (precise), wording second, otherwise 'other'."""
    group = icd_group(icd)
    if group and group != "other":
        return group
    return text_group(diagnosis) or group or "other"


def question_groups(question: str | None) -> set[str]:
    lowered = str(question or "").lower()
    groups: set[str] = set()
    for pattern, covered in _QUESTION_GROUPS:
        if re.search(pattern, lowered):
            groups.update(covered)
    return groups


def declared_groups(
    conditions: list,
    questionnaire: list[dict] | None = None,
) -> set[str]:
    """Every group the applicant has declared, by condition or by a Yes answer."""
    groups: set[str] = set()
    for condition in conditions or []:
        text = (
            " ".join(str(v) for v in condition.values() if v)
            if isinstance(condition, dict)
            else str(condition)
        )
        group = text_group(text)
        if group:
            groups.add(group)
    for item in questionnaire or []:
        answer = str(item.get("answer", "")).strip().lower()
        if answer not in {"yes", "y", "true"}:
            continue
        # The answer's own details say which condition it is (stones are not
        # chronic kidney disease); only an answer without details falls back
        # to the question's broad category.
        group = text_group(item.get("details"))
        if group:
            groups.add(group)
        else:
            groups |= question_groups(item.get("question"))
    return groups


def group_label(group: str) -> str:
    return GROUP_LABELS.get(group, group.replace("_", " "))