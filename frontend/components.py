from __future__ import annotations

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


def applicant_card(
    applicant: dict[str, Any],
) -> None:
    profile = applicant_profile_from(
        applicant
    )

    applicant_summary(
        applicant
    )

    # --------------------------------------------------------
    # MEDICAL PROFILE
    # --------------------------------------------------------

    section_title(
        "Medical Profile",
        "Declared medical conditions and current medications.",
    )

    conditions = get_list(
        profile,
        "medical_conditions",
        "conditions",
    )

    medications = get_list(
        profile,
        "medications",
    )

    left, right = st.columns(
        [1.35, 1],
        gap="large",
    )

    with left:
        st.markdown(
            "**Medical Conditions**"
        )

        if conditions:
            for condition in conditions:
                render_condition(
                    condition
                )
        else:
            st.caption(
                "No medical conditions declared."
            )

    with right:
        st.markdown(
            "**Current Medication**"
        )

        if medications:
            medication_items = []

            for medication in medications:
                if not isinstance(
                    medication,
                    dict,
                ):
                    continue

                name = get_value(
                    medication,
                    "name",
                    "medication",
                    default="",
                )

                details = get_value(
                    medication,
                    "details",
                    "dose",
                    default="",
                )

                if not name:
                    continue

                name = str(name).strip()

                # Remove obvious PDF extraction artifacts
                # that are actually medical conditions.
                if name.lower() in {
                    "gerd",
                    "hypertension",
                    "hypothyroidism",
                    "dyslipidaemia",
                    "intermittent",
                }:
                    continue

                medication_items.append(
                    (
                        name,
                        safe_text(
                            details,
                            "",
                        ),
                    )
                )

            if medication_items:
                medication_columns = st.columns(
                    3,
                    gap="medium",
                )

                for index, (
                    name,
                    details,
                ) in enumerate(
                    medication_items
                ):
                    with medication_columns[
                        index % 3
                    ]:
                        st.markdown(
                            f"**{name}**"
                        )

                        if details:
                            st.caption(
                                details
                            )

                        st.write("")
            else:
                st.caption(
                    "No current medications declared."
                )

        else:
            st.caption(
                "No current medications declared."
            )

    # --------------------------------------------------------
    # TREATMENT HISTORY
    # --------------------------------------------------------

    section_title(
        "Treatment History",
        "Hospitalization and day-care treatment history.",
    )

    hospitalizations = get_list(
        profile,
        "hospitalizations",
    )

    if hospitalizations:
        for index, hospitalization in enumerate(
            hospitalizations,
            start=1,
        ):
            render_hospitalization(
                hospitalization,
                index,
            )
    else:
        st.caption(
            "No hospitalization history declared."
        )

    # --------------------------------------------------------
    # CLAIMS
    # --------------------------------------------------------

    section_title(
        "Claims History",
        "Historical insurance claims declared in the submission.",
    )

    claims = get_list(
        profile,
        "claims",
    )

    if claims:
        st.caption(
            f"{len(claims)} historical claim(s) declared"
        )

        render_claims(
            claims
        )
    else:
        st.caption(
            "No historical claims declared."
        )

    # --------------------------------------------------------
    # EXISTING POLICY
    # --------------------------------------------------------

    section_title(
        "Existing Policy",
        "Current insurance policy information.",
    )

    policy = get_value(
        profile,
        "existing_policy",
        default={},
    )

    if isinstance(policy, dict) and policy:
        render_policy(
            policy
        )
    else:
        st.caption(
            "No existing policy declared."
        )


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

def evidence_item(
    item: Any,
    scope: str = "applicant",
) -> None:
    if isinstance(
        item,
        dict,
    ):
        title = get_value(
            item,
            "filename",
            "title",
            "document",
            "source",
            "name",
            default="Evidence",
        )

        text = get_value(
            item,
            "text",
            "content",
            "summary",
            "details",
            "page_content",
        )

        metadata = []

        for key in (
            "document_type",
            "source_type",
            "knowledge_type",
            "jurisdiction",
            "applicant_id",
        ):
            value = item.get(key)

            if value not in (
                None,
                "",
            ):
                metadata.append(
                    f"{key.replace('_', ' ').title()}: {value}"
                )

        st.markdown(
            f"**{safe_text(title)}**"
        )

        if metadata:
            st.caption(
                " · ".join(metadata)
            )

        if text:
            st.write(
                safe_text(text)
            )

    else:
        st.write(
            safe_text(item)
        )


def evidence_section(
    title: str,
    evidence: list[Any],
    scope: str = "applicant",
) -> None:
    if not evidence:
        return

    st.markdown(
        f"### {title}"
    )

    for item in evidence:
        evidence_item(
            item,
            scope=scope,
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
        placeholder=(
            "Document the basis for the review decision..."
        ),
        key=f"review_comments_{case_id}",
    )

    columns = st.columns(4)

    with columns[0]:
        approve = st.button(
            "Approve",
            key=f"approve_{case_id}",
            use_container_width=True,
        )

    with columns[1]:
        override = st.button(
            "Override",
            key=f"override_{case_id}",
            use_container_width=True,
        )

    with columns[2]:
        sendback = st.button(
            "Send Back",
            key=f"sendback_{case_id}",
            use_container_width=True,
        )

    with columns[3]:
        escalate = st.button(
            "Escalate",
            key=f"escalate_{case_id}",
            use_container_width=True,
        )

    if approve:
        return {
            "action": "approve",
            "reviewer": reviewer,
            "comments": comments,
        }

    if override:
        return {
            "action": "override",
            "reviewer": reviewer,
            "comments": comments,
        }

    if sendback:
        return {
            "action": "sendback",
            "reviewer": reviewer,
            "comments": comments,
        }

    if escalate:
        return {
            "action": "escalate",
            "reviewer": reviewer,
            "comments": comments,
        }

    return None