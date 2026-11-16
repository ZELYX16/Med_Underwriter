from __future__ import annotations

import re
from typing import Any

import streamlit as st

from styles import (
    metric_card,
    section_title,
    status_badge,
)


# ============================================================
# GENERIC HELPERS
# ============================================================

def get_value(
    data: Any,
    *keys: str,
    default: Any = None,
) -> Any:
    if not isinstance(data, dict):
        return default

    for key in keys:
        if key in data and data[key] is not None:
            return data[key]

    return default


def get_list(
    data: Any,
    *keys: str,
) -> list[Any]:
    value = get_value(
        data,
        *keys,
        default=[],
    )

    if isinstance(value, list):
        return value

    if value in (None, ""):
        return []

    return [value]


def normalize_response(
    response: Any,
) -> Any:
    if isinstance(response, dict):
        if response.get("success") is True:
            return response.get(
                "data",
                response,
            )

        if "data" in response:
            return response["data"]

    return response


def humanize(value: Any) -> str:
    if value is None:
        return ""
    text_value = str(value).strip()
    if not text_value:
        return ""
    return text_value.replace("_", " ").replace("-", " ").title()


def safe_text(
    value: Any,
    default: str = "—",
) -> str:
    if value is None:
        return default

    if isinstance(value, dict):
        parts = []

        for key, item in value.items():
            if item not in (None, ""):
                parts.append(
                    f"{key}: {item}"
                )

        return ", ".join(parts) or default

    if isinstance(value, list):
        if not value:
            return default

        parts = [
            safe_text(item, "")
            for item in value
            if item not in (None, "")
        ]

        return ", ".join(parts) or default

    text = str(value).strip()

    return text if text else default


def format_number(
    value: Any,
) -> str:
    if value is None:
        return "—"

    try:
        return f"{float(value):,.0f}"
    except (
        TypeError,
        ValueError,
    ):
        return safe_text(value)


def format_currency(
    value: Any,
    currency: str = "INR",
) -> str:
    if value is None:
        return "—"

    try:
        amount = float(value)
        return f"{currency} {amount:,.0f}"
    except (
        TypeError,
        ValueError,
    ):
        return safe_text(value)


def format_date(
    value: Any,
) -> str:
    if value in (None, ""):
        return "—"

    return str(value)


def normalized_status(
    status: Any,
) -> str:
    return (
        str(status or "unknown")
        .strip()
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )


def display_status(
    status: Any,
) -> str:
    return (
        normalized_status(status)
        .replace("-", " ")
        .title()
    )


def applicant_profile_from(
    applicant: dict[str, Any],
) -> dict[str, Any]:
    profile = applicant.get(
        "applicant_profile"
    )

    if isinstance(profile, dict):
        return profile

    return applicant


# ============================================================
# WORKSPACE
# ============================================================

WORKSPACE_SECTIONS = [
    "Overview",
    "Applicant",
    "Submission",
    "Evidence",
    "Agent 1",
    "Agent 2",
    "Agent 3 / Reflection",
    "Decision",
    "Workflow",
    "Human Review",
]


def render_workspace_toc(
    current: str = "Overview",
) -> str:
    if current not in WORKSPACE_SECTIONS:
        current = "Overview"

    st.markdown(
        "### Case Workspace"
    )

    columns = st.columns(4)

    for index, section in enumerate(
        WORKSPACE_SECTIONS
    ):
        column = columns[
            index % len(columns)
        ]

        with column:
            is_current = (
                section == current
            )

            if st.button(
                section,
                key=f"workspace_{section}",
                use_container_width=True,
                type=(
                    "primary"
                    if is_current
                    else "secondary"
                ),
            ):
                st.session_state.workspace_section = (
                    section
                )
                st.rerun()

    st.divider()

    return st.session_state.get(
        "workspace_section",
        current,
    )


# ============================================================
# APPLICANT
# ============================================================

def applicant_summary(
    applicant: dict[str, Any],
) -> None:
    """
    Compact applicant identity row.

    The page header already displays the applicant name,
    so this function intentionally does not repeat it.
    """

    profile = applicant_profile_from(
        applicant
    )

    applicant_id = get_value(
        applicant,
        "applicant_id",
        default=get_value(
            profile,
            "applicant_id",
        ),
    )

    age = get_value(
        profile,
        "age",
    )

    dob = get_value(
        profile,
        "date_of_birth",
        "dob",
    )

    source = get_value(
        profile,
        "source",
        default=get_value(
            applicant,
            "source",
        ),
    )

    source_text = safe_text(
        source
    ).replace(
        "_",
        " ",
    ).title()

    st.caption(
        f"{safe_text(applicant_id)}"
        f"  ·  Age {safe_text(age)}"
        f"  ·  DOB {safe_text(dob)}"
        f"  ·  {source_text}"
    )


_NOT_MEDICATIONS = {
    "gerd",
    "hypertension",
    "essential hypertension",
    "hypothyroidism",
    "dyslipidaemia",
    "type 2 diabetes mellitus",
    "intermittent",
}

_PERIOD = re.compile(
    r"^(\d{2}-[A-Za-z]{3}-\d{4}"
    r"(?:\s+to\s+\d{2}-[A-Za-z]{3}-\d{4})?"
    r"(?:\s+\(day-care\))?)\s*(.*)$",
    re.DOTALL,
)


def _clean_condition_name(name: Any) -> str:
    # PDF table headers sometimes get merged into the first cell.
    return (
        safe_text(name)
        .replace("Year diagnosed Status (as declared) ", "")
        .replace("injections ", "", 1)
        .strip()
    )


def _condition_rows(conditions: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for condition in conditions:
        if isinstance(condition, dict):
            rows.append(
                {
                    "Condition": _clean_condition_name(
                        get_value(condition, "condition", "name", default="Condition")
                    ),
                    "Since": safe_text(
                        get_value(condition, "year_diagnosed", "year", default=""), ""
                    ),
                    "Status": safe_text(
                        get_value(condition, "status", default=""), ""
                    ),
                }
            )
        else:
            rows.append(
                {"Condition": _clean_condition_name(condition), "Since": "", "Status": ""}
            )
    return rows


def _medication_rows(medications: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for medication in medications:
        if not isinstance(medication, dict):
            rows.append({"Medication": safe_text(medication), "Dose / frequency": ""})
            continue
        name = safe_text(
            get_value(medication, "name", "medication", default=""), ""
        ).strip()
        normalized = re.sub(r"\s+", " ", name.lower()).strip()
        if (
            not name
            or normalized in _NOT_MEDICATIONS
            or normalized.startswith("since ")
            or "year diagnosed" in normalized
            or "status (as declared)" in normalized
        ):
            continue
        rows.append(
            {
                "Medication": name,
                "Dose / frequency": safe_text(
                    get_value(medication, "details", "dose", default=""), ""
                ),
                "Indication": safe_text(
                    get_value(medication, "indication", default=""), ""
                ),
                "Duration": safe_text(
                    get_value(medication, "duration", default=""), ""
                ),
            }
        )
    return rows


def _hospitalization_rows(items: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        if isinstance(item, dict) and (item.get("reason") or item.get("facility")):
            rows.append(
                {
                    "Period": safe_text(item.get("period"), ""),
                    "Facility": safe_text(item.get("facility"), ""),
                    "Reason / procedure": safe_text(item.get("reason"), ""),
                    "Duration": safe_text(item.get("duration"), ""),
                }
            )
            continue
        details = safe_text(
            get_value(item, "details", default="")
            if isinstance(item, dict)
            else item,
            "",
        ).strip()
        match = _PERIOD.match(details)
        rows.append(
            {
                "Period": match.group(1) if match else "",
                "Details": (match.group(2) if match else details).strip(),
            }
        )
    return rows


def _table(rows: list[dict[str, Any]], empty: str) -> None:
    if rows:
        keep = [k for k in rows[0] if any(str(r.get(k, "")).strip() for r in rows)]
        rows = [{k: r.get(k, "") for k in keep} for r in rows]
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.caption(empty)


def applicant_card(
    applicant: dict[str, Any],
) -> None:
    profile = applicant_profile_from(applicant)

    applicant_summary(applicant)

    # --------------------------------------------------------
    # AT A GLANCE
    # --------------------------------------------------------

    smoker = profile.get("smoker")
    glance = [
        ("Age", safe_text(profile.get("age"), "-")),
        ("Date of birth", safe_text(profile.get("date_of_birth"), "-")),
        ("BMI", safe_text(profile.get("bmi"), "-")),
        (
            "Smoking",
            "Smoker" if smoker is True else "Non-smoker" if smoker is False else "-",
        ),
    ]
    for column, (label, value) in zip(st.columns(len(glance)), glance):
        with column:
            st.caption(label.upper())
            st.markdown(f"**{value}**")

    conditions = get_list(profile, "medical_conditions", "conditions")
    medications = get_list(profile, "medications")
    hospitalizations = get_list(profile, "hospitalizations")
    claims = get_list(profile, "claims")

    condition_rows = _condition_rows(conditions)
    medication_rows = _medication_rows(medications)

    # --------------------------------------------------------
    # MEDICAL PROFILE
    # --------------------------------------------------------

    section_title(
        "Medical Profile",
        f"{len(condition_rows)} declared condition(s), "
        f"{len(medication_rows)} current medication(s).",
    )

    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.markdown("**Medical conditions**")
        _table(condition_rows, "No medical conditions declared.")
    with right:
        st.markdown("**Current medication**")
        _table(medication_rows, "No current medications declared.")

    # --------------------------------------------------------
    # TREATMENT HISTORY
    # --------------------------------------------------------

    section_title(
        "Treatment History",
        "Hospitalization and day-care treatment history.",
    )
    _table(
        _hospitalization_rows(hospitalizations),
        "No hospitalization history declared.",
    )

    # --------------------------------------------------------
    # CLAIMS
    # --------------------------------------------------------

    section_title(
        "Claims History",
        "Historical insurance claims declared in the submission.",
    )
    claim_rows = []
    for claim in claims:
        if isinstance(claim, dict):
            claim_rows.append(
                {
                    "Claim": safe_text(get_value(claim, "claim_id", "id", default=""), ""),
                    "Date": safe_text(get_value(claim, "date", "claim_date", default=""), ""),
                    "Amount": safe_text(
                        get_value(claim, "amount", "claim_amount", default=""), ""
                    ),
                    "Status": safe_text(get_value(claim, "status", default=""), ""),
                }
            )
        else:
            claim_rows.append(
                {"Claim": safe_text(claim, ""), "Date": "", "Amount": "", "Status": ""}
            )
    # Hide columns that are empty for every claim.
    claim_rows = [
        {k: v for k, v in row.items() if any(r.get(k) for r in claim_rows)}
        for row in claim_rows
    ]
    _table(claim_rows, "No historical claims declared.")

    # --------------------------------------------------------
    # EXISTING POLICY
    # --------------------------------------------------------

    section_title(
        "Existing Policy",
        "Current insurance policy information.",
    )
    policy = get_value(profile, "existing_policy", default={})
    if isinstance(policy, dict) and any(policy.values()):
        sum_insured = policy.get("sum_insured")
        _table(
            [
                {
                    "Policy": safe_text(policy.get("policy_id"), "-"),
                    "Insurer": safe_text(policy.get("insurer"), ""),
                    "Sum insured": (
                        f"{float(sum_insured):,.0f}"
                        if isinstance(sum_insured, (int, float))
                        else ""
                    ),
                    "Status": safe_text(policy.get("status"), "-"),
                    "Claims declared": safe_text(policy.get("claims_declared"), ""),
                }
            ],
            "No existing policy declared.",
        )
    else:
        st.caption("No existing policy declared.")


def render_condition(
    condition: Any,
) -> None:
    if isinstance(condition, dict):
        name = safe_text(
            get_value(
                condition,
                "condition",
                "name",
                default="Condition",
            )
        )

        year = get_value(
            condition,
            "year_diagnosed",
            "year",
        )

        status = get_value(
            condition,
            "status",
        )

        # Clean known PDF extraction artifacts.
        name = (
            name
            .replace(
                "Year diagnosed Status (as declared) ",
                "",
            )
            .replace(
                "injections ",
                "",
                1,
            )
            .strip()
        )

        title = (
            f"{name} · {year}"
            if year
            else name
        )

        st.markdown(
            f"**{title}**"
        )

        if status:
            st.caption(
                safe_text(status)
            )

        st.write("")

    else:
        st.markdown(
            f"**{safe_text(condition)}**"
        )


def render_medication(
    medication: Any,
) -> None:
    if not isinstance(
        medication,
        dict,
    ):
        st.markdown(
            f"• {safe_text(medication)}"
        )
        return

    name = safe_text(
        get_value(
            medication,
            "name",
            "medication",
            default="Medication",
        )
    )

    details = get_value(
        medication,
        "details",
        "dose",
    )

    # Known PDF extraction artifacts.
    if name.lower() in {
        "gerd",
        "intermittent",
    }:
        return

    st.markdown(
        f"**{name}**"
    )

    if details:
        st.caption(
            safe_text(details)
        )

    st.write("")


def render_hospitalization(
    hospitalization: Any,
    index: int,
) -> None:
    if isinstance(
        hospitalization,
        dict,
    ):
        details = get_value(
            hospitalization,
            "details",
            default="",
        )
    else:
        details = hospitalization

    text = safe_text(
        details
    )

    # Keep each treatment record compact
    # while allowing long PDF-extracted text to wrap.
    columns = st.columns(
        [0.45, 7.55],
        gap="medium",
    )

    with columns[0]:
        st.caption(
            f"{index:02d}"
        )

    with columns[1]:
        st.write(
            text
        )

    if index < 999:
        st.write("")


def render_claims(
    claims: list[Any],
) -> None:
    rows = []

    for claim in claims:
        if isinstance(
            claim,
            dict,
        ):
            claim_id = get_value(
                claim,
                "claim_id",
                "id",
                default="Unknown",
            )

            status = get_value(
                claim,
                "status",
                default="Historical",
            )

            rows.append(
                {
                    "Claim": safe_text(
                        claim_id
                    ),
                    "Status": safe_text(
                        status
                    ).title(),
                }
            )

        else:
            rows.append(
                {
                    "Claim": safe_text(
                        claim
                    ),
                    "Status": "Historical",
                }
            )

    if not rows:
        return

    st.dataframe(
        rows,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Claim": st.column_config.TextColumn(
                "Claim",
                width="medium",
            ),
            "Status": st.column_config.TextColumn(
                "Status",
                width="medium",
            ),
        },
    )

    st.caption(
        "Claim IDs identify declared historical claims. "
        "Detailed claim information is available from "
        "the supporting claim documents used as applicant evidence."
    )


def render_policy(
    policy: dict[str, Any],
) -> None:
    policy_id = safe_text(
        get_value(
            policy,
            "policy_id",
        )
    )

    status = safe_text(
        get_value(
            policy,
            "status",
        )
    ).title()

    columns = st.columns(
        [1, 1],
        gap="large",
    )

    with columns[0]:
        st.caption(
            "POLICY ID"
        )
        st.markdown(
            f"**{policy_id}**"
        )

    with columns[1]:
        st.caption(
            "STATUS"
        )
        st.markdown(
            f"**{status}**"
        )


# ============================================================
# CASE CARDS
# ============================================================

def get_case_action(
    case: dict[str, Any],
) -> str:
    status = normalized_status(
        case.get("status")
    )

    if status in {
        "draft",
        "pending",
    }:
        return "Underwrite"

    if status in {
        "human-review",
        "review",
    }:
        return "Review"

    if status == "sent-back":
        return "Continue"

    return "View Case"


def case_card(
    case: dict[str, Any],
    show_action: bool = True,
) -> None:
    case_id = safe_text(
        case.get("case_id")
    )

    applicant_id = safe_text(
        case.get("applicant_id")
    )

    profile = case.get(
        "applicant_profile",
        {},
    )

    name = safe_text(
        get_value(
            profile,
            "name",
            default=case.get(
                "applicant_name",
                "Unknown Applicant",
            ),
        )
    )

    submission = case.get(
        "submission",
        {},
    )

    product = safe_text(
        get_value(
            submission,
            "product",
            default="Medical Insurance",
        )
    )

    status = normalized_status(
        case.get("status")
    )

    risk_score = get_value(
        case,
        "overall_risk_score",
    )

    st.markdown(
        '<div class="case-row">',
        unsafe_allow_html=True,
    )

    columns = st.columns(
        [1.15, 1.65, 2.4, 1.1, 1.25],
        gap="medium",
    )

    with columns[0]:
        st.caption("CASE")
        st.markdown(
            f"**{case_id}**"
        )
        st.caption(
            applicant_id
        )

    with columns[1]:
        st.caption("APPLICANT")
        st.markdown(
            f"**{name}**"
        )

    with columns[2]:
        st.caption("PRODUCT")
        st.write(
            product
        )

    with columns[3]:
        st.caption("STATUS")

        st.markdown(
            status_badge(
                status,
                display_status(status),
            ),
            unsafe_allow_html=True,
        )

        if risk_score is not None:
            st.caption(
                f"Risk {safe_text(risk_score)}"
            )

    with columns[4]:
        if show_action:
            action = get_case_action(
                case
            )

            if st.button(
                action,
                key=f"case_action_{case_id}",
                use_container_width=True,
            ):
                st.session_state.selected_case_id = (
                    case_id
                )

                if action == "Review":
                    st.session_state.page = (
                        "review"
                    )
                else:
                    st.session_state.page = (
                        "case"
                    )

                st.session_state.workspace_section = (
                    "Overview"
                )

                st.rerun()

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )


# ============================================================
# CASE HEADER
# ============================================================

def case_header(
    case: dict[str, Any],
) -> None:
    case_id = safe_text(
        case.get("case_id")
    )

    profile = case.get(
        "applicant_profile",
        {},
    )

    submission = case.get(
        "submission",
        {},
    )

    name = safe_text(
        get_value(
            profile,
            "name",
            default="Unknown Applicant",
        )
    )

    status = normalized_status(
        case.get("status")
    )

    risk = get_value(
        case,
        "overall_risk_score",
    )

    st.markdown(
        f"# {case_id}"
    )

    st.caption(
        f"{name} · {display_status(status)}"
    )

    columns = st.columns(5)

    values = [
        (
            "Applicant",
            name,
        ),
        (
            "Product",
            get_value(
                submission,
                "product",
                default="—",
            ),
        ),
        (
            "Sum Insured",
            format_currency(
                get_value(
                    submission,
                    "sum_insured",
                )
            ),
        ),
        (
            "Policy Type",
            get_value(
                submission,
                "policy_type",
                default="—",
            ),
        ),
        (
            "Risk Score",
            (
                risk
                if risk is not None
                else "Pending"
            ),
        ),
    ]

    for column, (label, value) in zip(
        columns,
        values,
    ):
        with column:
            metric_card(
                label,
                safe_text(value),
            )


# ============================================================
# SUBMISSION
# ============================================================

def submission_summary(
    submission: dict[str, Any],
) -> None:
    if not submission:
        st.info(
            "No underwriting submission information available."
        )
        return

    term_years = get_value(
        submission,
        "term_years",
    )

    term = (
        f"{term_years} year(s)"
        if term_years
        else "—"
    )

    fields = [
        (
            "Product",
            get_value(
                submission,
                "product",
            ),
        ),
        (
            "Policy Type",
            get_value(
                submission,
                "policy_type",
            ),
        ),
        (
            "Sum Insured",
            format_currency(
                get_value(
                    submission,
                    "sum_insured",
                )
            ),
        ),
        (
            "Term",
            term,
        ),
        (
            "Requested Start",
            get_value(
                submission,
                "requested_start_date",
            ),
        ),
        (
            "Jurisdiction",
            get_value(
                submission,
                "jurisdiction",
            ),
        ),
        (
            "Insurer",
            get_value(
                submission,
                "insurer",
            ),
        ),
    ]

    columns = st.columns(4)

    for index, (label, value) in enumerate(
        fields
    ):
        with columns[
            index % len(columns)
        ]:
            st.caption(label)
            st.write(
                safe_text(value)
            )


# ============================================================
# RISK
# ============================================================

def risk_summary(
    risk_assessment: dict[str, Any],
) -> None:
    if not risk_assessment:
        st.info(
            "Risk assessment is not available yet."
        )
        return

    fields = [
        (
            "Overall Risk",
            get_value(
                risk_assessment,
                "overall_risk_score",
            ),
        ),
        (
            "Medical Risk",
            get_value(
                risk_assessment,
                "medical_risk_score",
            ),
        ),
        (
            "Claims Risk",
            get_value(
                risk_assessment,
                "claims_risk_score",
            ),
        ),
        (
            "Coverage Gap",
            get_value(
                risk_assessment,
                "coverage_gap_score",
            ),
        ),
    ]

    columns = st.columns(4)

    for column, (label, value) in zip(
        columns,
        fields,
    ):
        with column:
            metric_card(
                label,
                (
                    safe_text(value)
                    if value is not None
                    else "Pending"
                ),
            )


def risk_factors(
    factors: list[Any],
) -> None:
    if not factors:
        st.info(
            "No specific risk factors recorded."
        )
        return

    for index, factor in enumerate(
        factors,
        start=1,
    ):
        if isinstance(
            factor,
            dict,
        ):
            title = get_value(
                factor,
                "factor",
                "name",
                "title",
                default=f"Risk factor {index}",
            )

            description = get_value(
                factor,
                "description",
                "reason",
                "details",
            )

            st.markdown(
                f"**{index}. {safe_text(title)}**"
            )

            if description:
                st.write(
                    safe_text(description)
                )

        else:
            st.markdown(
                f"**{index}.** "
                f"{safe_text(factor)}"
            )


# ============================================================
# EVIDENCE
# ============================================================

def _source_name(value: Any) -> str:
    raw = safe_text(value).strip()
    if not raw:
        return "Evidence"

    # Handles both Windows and POSIX paths without exposing local directories.
    raw = raw.replace("\\", "/")
    return raw.rsplit("/", 1)[-1] or "Evidence"


def _evidence_text(item: Any) -> str:
    if not isinstance(item, dict):
        return safe_text(item).strip()

    value = get_value(
        item,
        "text",
        "content",
        "summary",
        "details",
        "page_content",
        default="",
    )
    return safe_text(value).strip()


def _evidence_meta(item: dict[str, Any]) -> str:
    parts = []
    document_type = item.get("document_type")
    jurisdiction = item.get("jurisdiction")
    applicant_id = item.get("applicant_id")
    page = item.get("page") or item.get("page_number")
    source_type = item.get("source_type")

    if document_type:
        parts.append(str(document_type).replace("_", " ").title())
    if jurisdiction:
        parts.append(f"Jurisdiction: {jurisdiction}")
    if applicant_id:
        parts.append(f"Applicant: {applicant_id}")
    if page:
        parts.append(f"Page {page}")
    if source_type:
        parts.append(str(source_type).replace("_", " ").title())

    return " · ".join(parts)


def evidence_item(
    item: Any,
    scope: str = "applicant",
    compact: bool = True,
) -> None:
    if isinstance(item, dict):
        source = get_value(
            item,
            "filename",
            "title",
            "document",
            "source",
            "name",
            default="Evidence",
        )
        title = _source_name(source)
        content = _evidence_text(item)
        meta = _evidence_meta(item)

        if compact:
            with st.expander(title, expanded=False):
                if meta:
                    st.caption(meta)
                if content:
                    st.write(content)
                else:
                    st.caption("No extracted text available.")
        else:
            st.markdown(f"**{safe_text(title)}**")
            if meta:
                st.caption(meta)
            if content:
                st.write(content)
    else:
        st.write(safe_text(item))


def _evidence_scope_label(scope: Any) -> str:
    value = str(scope or "applicant").strip().lower()
    return {
        "applicant": "Applicant Evidence",
        "knowledge": "Medical Knowledge",
        "regulatory": "Regulatory Evidence",
        "underwriting": "Underwriting Guidance",
    }.get(value, value.replace("_", " ").title())


def _evidence_reason(scope: Any, document_type: Any) -> str:
    scope_key = str(scope or "applicant").strip().lower()
    type_key = str(document_type or "").strip().lower()

    if scope_key == "regulatory":
        return (
            "Supports regulatory compliance and underwriting-policy "
            "requirements for the case jurisdiction."
        )
    if scope_key == "knowledge":
        return (
            "Provides medical reference knowledge used to interpret "
            "clinical conditions, treatments, or terminology."
        )
    if type_key == "medical":
        return (
            "Primary applicant evidence used to establish diagnoses, "
            "treatment status, medications, and clinical stability."
        )
    if type_key == "claims":
        return (
            "Applicant evidence used to establish historical claims, "
            "utilization, hospitalization, and treatment patterns."
        )
    if type_key == "policy":
        return (
            "Applicant evidence used to establish existing coverage, "
            "policy status, and relevant coverage terms."
        )
    if type_key == "underwriting":
        return (
            "Submission or underwriting evidence used to establish the "
            "requested product, declarations, and underwriting context."
        )
    return (
        "Source evidence retrieved by the underwriting workflow and "
        "available for reviewer verification."
    )


def _document_label(item: dict[str, Any]) -> str:
    return _source_name(
        get_value(
            item,
            "filename",
            "file_name",
            "title",
            "document",
            "source",
            default="Evidence document",
        )
    )


def _clean_evidence_text(value: Any) -> str:
    text = safe_text(value, "").strip()
    if not text:
        return ""

    # Normalize escaped newlines and common PDF extraction artifacts.
    text = text.replace("\\n", "\n")
    text = re.sub(r"\[Page\s+\d+\]", "", text, flags=re.I)
    text = re.sub(r"\bPage\s+\d+\s+of\s+\d+\b", "", text, flags=re.I)

    # Remove repeated synthetic document headers while keeping their actual
    # clinical content.
    text = re.sub(
        r"\bAPP-\d+\s+SYNTHETIC\s*/?\s*DEMONSTRATION DATA\s*[—-]\s*MEDUNDERWRITE AI\b",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(?:Medical|Endocrinology|Claim|Policy|Underwriting)\s+Report\s+[^|\n]+\|\s*APP-\d+[^\n]*",
        "",
        text,
        flags=re.I,
    )

    # Turn numbered report sections into readable blocks.
    text = re.sub(r"\s+(?=\d+\.\s+[A-Z])", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)

    return text.strip(" \n")


def _document_content(item: dict[str, Any]) -> str:
    value = get_value(
        item,
        "human_readable_content",
        "original_text",
        "full_text",
        "clean_text",
        "content",
        "text",
        "page_content",
        "excerpt",
        default="",
    )
    return _clean_evidence_text(value)


def _dedupe_evidence_fragments(contents: list[str]) -> list[str]:
    """Remove exact and containment duplicates caused by overlapping retrieval chunks."""
    normalized: list[str] = []
    seen: set[str] = set()

    for value in contents:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)

    # Prefer the longest version when one retrieved fragment is wholly
    # contained in another fragment from the same source document.
    normalized.sort(key=len, reverse=True)
    kept: list[str] = []
    for candidate in normalized:
        candidate_key = candidate.casefold()
        if any(candidate_key in existing.casefold() for existing in kept):
            continue
        kept.append(candidate)

    return list(reversed(kept))


def _render_document_reader(
    title: str,
    items: list[Any],
    scope: str,
) -> None:
    if not items:
        return

    first = next(
        (
            item
            for item in items
            if isinstance(item, dict)
        ),
        {},
    )

    document_type = get_value(
        first,
        "document_type",
        "type",
        default="",
    )
    applicant_id = get_value(
        first,
        "applicant_id",
        default="",
    )

    contents: list[str] = []
    seen: set[str] = set()

    for item in items:
        content = (
            _document_content(item)
            if isinstance(item, dict)
            else safe_text(item, "")
        )
        if content and content not in seen:
            seen.add(content)
            contents.append(content)

    contents = _dedupe_evidence_fragments(contents)
    full_text = "\n\n".join(contents).strip()

    st.markdown(
        f"**{title}**"
    )

    meta_parts = [
        _evidence_scope_label(scope),
    ]
    if document_type:
        meta_parts.append(humanize(document_type))
    if applicant_id:
        meta_parts.append(f"Applicant {safe_text(applicant_id)}")

    st.caption(" · ".join(meta_parts))

    st.markdown(
        "**Why this evidence matters**"
    )
    st.write(
        _evidence_reason(
            scope,
            document_type,
        )
    )

    if full_text:
        st.markdown(
            "**Relevant evidence**"
        )
        if len(full_text) <= 1800:
            # Short enough to show whole; a second "full text" copy is noise.
            st.write(full_text)
        else:
            st.write(full_text[:1800].strip() + "…")
            with st.expander(
                "View full source text",
                expanded=False,
            ):
                st.text(full_text)
                st.caption(
                    "Readable source-document text is shown here for reviewer verification. "
                    "Retrieval chunks remain an AI representation; they are not presented as the original PDF."
                )
    else:
        st.caption(
            "The source was retrieved, but readable text is not available."
        )


def evidence_item(
    item: Any,
    scope: str = "applicant",
    compact: bool = False,
) -> None:
    if isinstance(item, dict):
        title = _document_label(item)
        _render_document_reader(
            title,
            [item],
            scope,
        )
    else:
        _render_document_reader(
            "Evidence document",
            [item],
            scope,
        )


def evidence_section(
    title: str,
    evidence: list[Any],
    scope: str = "applicant",
) -> None:
    if not evidence:
        return

    st.markdown(f"### {title}")

    groups: dict[str, list[Any]] = {}
    for item in evidence:
        if isinstance(item, dict):
            source = get_value(
                item,
                "filename",
                "file_name",
                "title",
                "document",
                "source",
                "name",
                default="Evidence",
            )
            group_name = _source_name(source)
        else:
            group_name = "Retrieved evidence"
        groups.setdefault(group_name, []).append(item)

    for group_name, items in groups.items():
        _render_document_reader(
            group_name,
            items,
            scope,
        )


def evidence_availability(
    evidence: dict[str, Any],
) -> None:
    if not evidence:
        st.info(
            "No evidence has been retrieved."
        )
        return

    applicant_count = 0
    knowledge_count = 0
    regulatory_count = 0

    for key, value in evidence.items():
        if not isinstance(
            value,
            list,
        ):
            continue

        count = len(value)
        lower_key = key.lower()

        if "regulat" in lower_key:
            regulatory_count += count

        elif any(
            word in lower_key
            for word in (
                "medical",
                "claim",
                "policy",
                "applicant",
                "submission",
            )
        ):
            applicant_count += count

        else:
            knowledge_count += count

    columns = st.columns(3)

    with columns[0]:
        metric_card(
            "Applicant Evidence",
            applicant_count,
        )

    with columns[1]:
        metric_card(
            "Knowledge Evidence",
            knowledge_count,
        )

    with columns[2]:
        metric_card(
            "Regulatory Evidence",
            regulatory_count,
        )


# ============================================================
# AGENT RESULTS
# ============================================================

def agent_result(
    title: str,
    result: Any,
) -> None:
    st.markdown(
        f"### {title}"
    )

    if result in (
        None,
        {},
        [],
        "",
    ):
        st.info(
            "No result recorded."
        )
        return

    if isinstance(
        result,
        dict,
    ):
        preferred_sections = [
            "summary",
            "findings",
            "risk_factors",
            "recommendation",
            "reasoning_summary",
            "confidence",
            "decision",
        ]

        rendered = set()

        for key in preferred_sections:
            if key not in result:
                continue

            value = result[key]

            if value in (
                None,
                "",
                [],
                {},
            ):
                continue

            st.markdown(
                f"**{key.replace('_', ' ').title()}**"
            )

            if isinstance(
                value,
                (dict, list),
            ):
                st.json(value)
            else:
                st.write(
                    safe_text(value)
                )

            rendered.add(key)

        remaining = {
            key: value
            for key, value in result.items()
            if key not in rendered
        }

        if remaining:
            with st.expander(
                "Additional agent output",
                expanded=False,
            ):
                st.json(
                    remaining
                )

    elif isinstance(
        result,
        (list, tuple),
    ):
        for item in result:
            st.write(
                safe_text(item)
            )

    else:
        st.write(
            safe_text(result)
        )



def _metric_number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _metric_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def agent_metrics(
    agent: dict[str, Any] | None,
    agent_name: str = "Agent",
) -> None:
    data = agent if isinstance(agent, dict) else {}

    latency = _metric_number(
        data.get("latency_sec")
    )
    llm_latency = _metric_number(
        data.get("llm_latency_sec")
    )
    input_tokens = _metric_int(
        data.get("input_tokens")
    )
    output_tokens = _metric_int(
        data.get("output_tokens")
    )
    total_tokens = _metric_int(
        data.get("total_tokens")
    )

    if not data or not any((latency, llm_latency, input_tokens, output_tokens, total_tokens)):
        return

    st.markdown(
        f"#### {agent_name} Metrics"
    )

    columns = st.columns(5)
    values = [
        ("Latency", f"{latency:.4f}s"),
        ("LLM Latency", f"{llm_latency:.4f}s"),
        ("Input Tokens", f"{input_tokens:,}"),
        ("Output Tokens", f"{output_tokens:,}"),
        ("Total Tokens", f"{total_tokens:,}"),
    ]

    for column, (label, value) in zip(columns, values):
        with column:
            metric_card(label, value)


def text_of_status(values: dict[str, Any]) -> str:
    status = values.get("llm_status")
    if status:
        error = values.get("llm_error")
        return f"{status}: {error}" if error else str(status)
    return "Used" if values.get("llm_used") else "Not used"


def _timing(values: dict[str, Any], key: str, suffix: str = "s") -> str:
    timing = values.get("timing")
    value = timing.get(key) if isinstance(timing, dict) else None
    if value is None:
        return "-"
    return f"{value}{suffix}"


def _cache_label(values: dict[str, Any]) -> str:
    events = values.get("cache_events")
    if isinstance(events, list) and events:
        hits = sum(1 for e in events if e.get("outcome") == "hit")
        misses = sum(1 for e in events if e.get("outcome") == "miss")
        skipped = sum(1 for e in events if e.get("outcome") == "skipped")
        parts = []
        if hits:
            parts.append(f"{hits} hit")
        if misses:
            parts.append(f"{misses} miss")
        if skipped:
            parts.append("skipped")
        return ", ".join(parts) or "-"
    if values.get("cache_hit"):
        return "1 hit"
    return "-"


def workflow_metrics(
    metrics: dict[str, Any] | None,
) -> None:
    data = metrics if isinstance(metrics, dict) else {}
    agents = data.get("agents")
    if not isinstance(agents, dict):
        agents = {}

    def has_data(values: dict[str, Any]) -> bool:
        return any(
            _metric_number(values.get(k))
            for k in (
                "workflow_latency_sec",
                "latency_sec",
                "llm_latency_sec",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "data_input_tokens",
                "data_output_tokens",
                "data_total_tokens",
            )
        )

    agent_rows = {
        name: values
        for name, values in agents.items()
        if isinstance(values, dict) and has_data(values)
    }
    if not has_data(data) and not agent_rows:
        return

    # Older runs have no data_* fields; fall back to summing the agents.
    def data_total(key: str) -> int:
        value = _metric_int(data.get(key))
        if value:
            return value
        return sum(_metric_int(v.get(key)) for v in agent_rows.values())

    if has_data(data):
        st.markdown("#### Workflow Metrics")
        st.caption(
            "All = everything the agents read and produced (estimated, ~4 characters per token). "
            "LLM = what the model actually used; 0 for steps that make no LLM call. "
            "Agents that re-ran after a reflection rescore show the sum of all runs (see Runs)."
        )
        row1 = st.columns(4)
        llm_latency = _metric_number(data.get("llm_latency_sec")) or sum(
            _metric_number(v.get("llm_latency_sec")) for v in agent_rows.values()
        )
        for column, (label, value) in zip(
            row1,
            (
                ("Total Latency", f"{_metric_number(data.get('workflow_latency_sec')):.4f}s"),
                ("LLM Latency", f"{llm_latency:.4f}s"),
                ("All Tokens (in / out)", f"{data_total('data_input_tokens'):,} / {data_total('data_output_tokens'):,}"),
                ("All Tokens (total)", f"{data_total('data_total_tokens'):,}"),
            ),
        ):
            with column:
                metric_card(label, value)

        row2 = st.columns(3)
        for column, (label, value) in zip(
            row2,
            (
                ("LLM Input Tokens", f"{_metric_int(data.get('input_tokens')):,}"),
                ("LLM Output Tokens", f"{_metric_int(data.get('output_tokens')):,}"),
                ("LLM Total Tokens", f"{_metric_int(data.get('total_tokens')):,}"),
            ),
        ):
            with column:
                metric_card(label, value)

    if agent_rows:
        st.markdown("##### Agent Usage")
        rows = []
        for name, values in agent_rows.items():
            rows.append({
                "Agent": humanize(name),
                "Runs": _metric_int(values.get("runs")) or 1,
                "Latency": f"{_metric_number(values.get('latency_sec')):.4f}s",
                "Data In": _metric_int(values.get("data_input_tokens")),
                "Data Out": _metric_int(values.get("data_output_tokens")),
                "Data Total": _metric_int(values.get("data_total_tokens")),
                "LLM Status": text_of_status(values),
                "LLM Latency": f"{_metric_number(values.get('llm_latency_sec')):.4f}s",
                "Model Load": _timing(values, "load_sec"),
                "Generation": _timing(values, "generation_sec"),
                "Tokens/sec": _timing(values, "tokens_per_sec", suffix=""),
                "LLM In": _metric_int(values.get("input_tokens")),
                "LLM Out": _metric_int(values.get("output_tokens")),
                "LLM Total": _metric_int(values.get("total_tokens")),
                "Cache": _cache_label(values),
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)

        stats = (agent_rows.get("agent1") or {}).get("evidence_stats")
        if isinstance(stats, dict) and stats.get("unique_chunks") is not None:
            st.caption(
                f"Agent 1 retrieved {stats.get('unique_chunks')} unique evidence "
                f"chunk(s) (~{_metric_int(stats.get('unique_chars')):,} characters). "
                f"The saved result carries {stats.get('stored_copies')} copies "
                f"({stats.get('duplicate_copies')} duplicate), which is a storage "
                "layout for the UI, not extra retrieval."
            )


# ============================================================
# WORKFLOW
# ============================================================

def workflow_timeline(
    events: list[Any],
) -> None:
    if not events:
        st.info(
            "No workflow events recorded yet."
        )
        return

    for index, event in enumerate(
        events,
        start=1,
    ):
        if isinstance(
            event,
            dict,
        ):
            node = get_value(
                event,
                "node",
                "event_type",
                default="Workflow",
            )

            status = get_value(
                event,
                "status",
                default="",
            )

            message = get_value(
                event,
                "message",
                default="",
            )

            timestamp = get_value(
                event,
                "timestamp",
                "created_at",
            )

            title = (
                f"{index:02d} · "
                f"{safe_text(node)}"
            )

            if status:
                title += (
                    f" · {display_status(status)}"
                )

            st.markdown(
                f"**{title}**"
            )

            if timestamp:
                st.caption(
                    safe_text(timestamp)
                )

            if message:
                st.write(
                    safe_text(message)
                )

        else:
            st.write(
                safe_text(event)
            )


# ============================================================
# HUMAN REVIEW
# ============================================================

def review_summary(
    reviews: list[Any],
) -> None:
    if not reviews:
        st.info(
            "No human review actions recorded."
        )
        return

    for review in reviews:
        if not isinstance(
            review,
            dict,
        ):
            st.write(
                safe_text(review)
            )
            continue

        action = get_value(
            review,
            "action",
            default="Review",
        )

        reviewer = get_value(
            review,
            "reviewer",
        )

        comment = get_value(
            review,
            "comment",
            "comments",
        )

        decision = get_value(
            review,
            "decision",
        )

        timestamp = get_value(
            review,
            "created_at",
            "timestamp",
        )

        st.markdown(
            f"**{display_status(action)}**"
        )

        if reviewer:
            st.caption(
                f"Reviewer: {safe_text(reviewer)}"
            )

        if decision:
            st.write(
                f"Decision: {safe_text(decision)}"
            )

        if comment:
            st.write(
                safe_text(comment)
            )

        if timestamp:
            st.caption(
                safe_text(timestamp)
            )

        st.divider()


def review_actions(
    case_id: str,
) -> dict[str, Any] | None:
    reviewer = st.text_input(
        "Reviewer",
        value="Underwriter",
        key=f"reviewer_{case_id}",
    )

    comments = st.text_area(
        "Review comments",
        placeholder="Document the basis for the review decision...",
        key=f"review_comments_{case_id}",
    )

    decision = st.selectbox(
        "Override decision",
        options=[
            "approved",
            "approved_with_loading",
            "approved_with_exclusion",
            "postpone",
            "declined",
        ],
        format_func=humanize,
        key=f"override_decision_{case_id}",
    )

    columns = st.columns(4)

    with columns[0]:
        approve = st.button("Approve", key=f"approve_{case_id}", use_container_width=True)
    with columns[1]:
        override = st.button("Override", key=f"override_{case_id}", use_container_width=True)
    with columns[2]:
        sendback = st.button("Send Back", key=f"sendback_{case_id}", use_container_width=True)
    with columns[3]:
        escalate = st.button("Escalate", key=f"escalate_{case_id}", use_container_width=True)

    reviewer = reviewer.strip()
    comments = comments.strip()

    if approve:
        return {"action": "approve", "reviewer": reviewer, "comments": comments}
    if override:
        return {
            "action": "override",
            "reviewer": reviewer,
            "comments": comments,
            "decision": decision,
        }
    if sendback:
        if not comments:
            st.warning("Add review comments before sending the case back.")
            return None
        return {"action": "sendback", "reviewer": reviewer, "comments": comments}
    if escalate:
        if not comments:
            st.warning("Add review comments before escalating the case.")
            return None
        return {"action": "escalate", "reviewer": reviewer, "comments": comments}

    return None