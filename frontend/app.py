# frontend/app.py

from __future__ import annotations

import html
import time
from typing import Any

import streamlit as st

from api_client import APIError, api
from components import (
    applicant_card,
    evidence_availability,
    evidence_section,
    get_list,
    agent_metrics,
    workflow_metrics,
    normalize_response,
    review_actions,
    review_summary,
    risk_factors,
    workflow_timeline,
)
from config import settings
from styles import (
    footer,
    inject_css,
    page_header,
    section_title,
    status_badge,
)


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="MedUnderwrite AI",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()


# ============================================================
# SESSION STATE
# ============================================================

DEFAULTS = {
    "page": "dashboard",
    "selected_case_id": None,
    "selected_applicant_id": None,
    "workspace_section": "Overview",
    "case_cache": {},
    "applicant_cache": {},
    "underwriting_running": False,
    "last_refresh": 0.0,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# GENERAL HELPERS
# ============================================================

def esc(value: Any) -> str:
    return html.escape(
        str(value if value is not None else "")
    )


def text(
    value: Any,
    default: str = "—",
) -> str:
    if value is None or value == "":
        return default

    if isinstance(value, float):
        return f"{value:,.2f}"

    if isinstance(value, int):
        return f"{value:,}"

    return str(value)


def humanize(value: Any) -> str:
    if value is None:
        return "—"

    value = str(value).strip()

    if not value:
        return "—"

    replacements = {
        "accept_with_loading": "Accept with Loading",
        "standard_acceptance": "Standard Acceptance",
        "approved_with_loading": "Approved with Loading",
        "approved": "Approved",
        "declined": "Declined",
        "decline": "Decline",
        "accept": "Accept",
        "accepted": "Accepted",
        "human_review": "Human Review",
        "sent_back": "Sent Back",
        "in_progress": "In Progress",
        "coverage_gap": "Coverage Gap",
        "full_mar": "Full Multi-Agent Reflection",
        "targeted": "Targeted Reflection",
        "lightweight": "Lightweight Reflection",
        "medical_accuracy": "Medical Accuracy",
        "actuarial_soundness": "Actuarial Soundness",
        "regulatory_compliance": "Regulatory Compliance",
        "customer_advocate": "Customer Advocate",
        "medical_expert": "Medical Expert",
        "compliance_officer": "Compliance Officer",
    }

    if value.lower() in replacements:
        return replacements[value.lower()]

    return (
        value.replace("_", " ")
        .replace("-", " ")
        .strip()
        .title()
    )


def status_key(value: Any) -> str:
    return (
        str(value or "unknown")
        .strip()
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )


def status_label(value: Any) -> str:
    return humanize(value)


def normalize_data(response: Any) -> Any:
    try:
        return normalize_response(response)
    except Exception:
        if isinstance(response, dict):
            return response.get("data", response)
        return response


def list_from(response: Any) -> list[dict[str, Any]]:
    data = normalize_data(response)

    if isinstance(data, list):
        return [
            item
            for item in data
            if isinstance(item, dict)
        ]

    if not isinstance(data, dict):
        return []

    for key in (
        "items",
        "cases",
        "applicants",
        "documents",
        "events",
        "reviews",
    ):
        value = data.get(key)

        if isinstance(value, list):
            return [
                item
                for item in value
                if isinstance(item, dict)
            ]

    return []


def profile_from_case(
    case: dict[str, Any],
) -> dict[str, Any]:
    profile = case.get("applicant_profile")

    if isinstance(profile, dict):
        return profile

    state = case.get("state")

    if isinstance(state, dict):
        profile = state.get("applicant_profile")

        if isinstance(profile, dict):
            return profile

    return {}


def applicant_name(
    case: dict[str, Any],
) -> str:
    profile = profile_from_case(case)

    return str(
        profile.get("name")
        or case.get("applicant_name")
        or "Unknown Applicant"
    )


def applicant_id(
    case: dict[str, Any],
) -> str:
    profile = profile_from_case(case)

    return str(
        case.get("applicant_id")
        or profile.get("applicant_id")
        or ""
    )


def submission_from_case(
    case: dict[str, Any],
) -> dict[str, Any]:
    submission = case.get("submission")

    if isinstance(submission, dict):
        return submission

    state = case.get("state")

    if isinstance(state, dict):
        submission = state.get("submission")

        if isinstance(submission, dict):
            return submission

    return {}


def product(
    case: dict[str, Any],
) -> str:
    submission = submission_from_case(case)

    return str(
        submission.get("product")
        or "Medical Insurance"
    )


def risk_assessment(
    case: dict[str, Any],
) -> dict[str, Any]:
    value = case.get("risk_assessment")

    if isinstance(value, dict):
        return value

    state = case.get("state")

    if isinstance(state, dict):
        value = state.get("risk_assessment")

        if isinstance(value, dict):
            return value

    return {}


def risk_value(
    case: dict[str, Any],
    field: str,
) -> Any:
    value = case.get(field)

    if value is not None:
        return value

    risk = risk_assessment(case)

    if field in risk:
        return risk.get(field)

    agent2 = get_agent_result(
        case,
        2,
    )

    return agent2.get(field)


def overall_risk(
    case: dict[str, Any],
) -> Any:
    return risk_value(
        case,
        "overall_risk_score",
    )


def recommendation(
    case: dict[str, Any],
) -> str:
    candidates = [
        case.get("final_recommendation"),
        case.get("recommendation"),
        case.get("agent2_recommendation"),
        risk_assessment(case).get("recommendation"),
        risk_assessment(case).get("final_recommendation"),
        get_agent_result(case, 2).get("recommendation"),
    ]

    for value in candidates:
        if value not in (
            None,
            "",
        ):
            return humanize(value)

    return "Pending"


def decision(
    case: dict[str, Any],
) -> str:
    value = case.get("final_decision")

    if isinstance(value, dict):
        for key in (
            "decision",
            "status",
            "outcome",
        ):
            if value.get(key):
                return humanize(
                    value.get(key)
                )

    if value:
        return humanize(value)

    return "Pending"


def risk_band(
    score: Any,
) -> str:
    if score is None or score == "":
        return "Pending"

    try:
        value = float(score)
    except (
        TypeError,
        ValueError,
    ):
        return "Pending"

    if value >= 70:
        return "High"

    if value >= 45:
        return "Moderate"

    return "Low"


def risk_display(
    score: Any,
) -> str:
    if score is None or score == "":
        return "Pending"

    try:
        return f"{float(score):.0f}"
    except (
        TypeError,
        ValueError,
    ):
        return str(score)


def format_currency(
    value: Any,
    currency: str = "INR",
) -> str:
    if value is None or value == "":
        return "—"

    try:
        amount = float(value)
        return f"{currency} {amount:,.0f}"
    except (
        TypeError,
        ValueError,
    ):
        return str(value)


def open_case(
    case_id: str,
    section: str = "Overview",
) -> None:
    st.session_state.selected_case_id = case_id
    st.session_state.workspace_section = section
    st.session_state.page = "case"
    st.rerun()


def open_applicant(
    applicant_id_value: str,
) -> None:
    st.session_state.selected_applicant_id = (
        applicant_id_value
    )
    st.session_state.page = "applicant"
    st.rerun()


def render_empty(
    title: str,
    message: str,
) -> None:
    st.info(
        f"**{title}**\n\n{message}"
    )


# ============================================================
# AGENT HELPERS
# ============================================================

def _dict_value(
    source: Any,
    *keys: str,
) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}

    for key in keys:
        value = source.get(key)

        if isinstance(value, dict):
            return value

    return {}


def get_agent_result(
    case: dict[str, Any],
    number: int,
) -> dict[str, Any]:
    keys = {
        1: (
            "agent1",
            "agent_1",
            "agent1_result",
            "agent_1_result",
            "agent1_output",
            "agent_1_output",
        ),
        2: (
            "agent2",
            "agent_2",
            "agent2_result",
            "agent_2_result",
            "agent2_output",
            "agent_2_output",
        ),
        3: (
            "agent3",
            "agent_3",
            "agent3_result",
            "agent_3_result",
            "agent3_output",
            "agent_3_output",
            "reflection",
            "reflection_result",
            "constitutional_results",
        ),
    }

    result = _dict_value(
        case,
        *keys[number],
    )

    # Current backend stores Agent 1 output as agent1_enrichment,
    # Agent 2 output as risk_assessment, and Agent 3 output across
    # reflection/constitutional top-level fields.
    if not result and number == 1:
        enrichment = case.get("agent1_enrichment")
        if isinstance(enrichment, dict):
            result = enrichment

    if not result and number == 2:
        assessment = case.get("risk_assessment")
        if isinstance(assessment, dict):
            result = assessment

    if not result and number == 3:
        result = {}
        for field in (
            "reflection_findings",
            "reflection_verdict",
            "reflection_requires_rescore",
            "reflection_type",
            "reflection_personas",
            "require_human_review",
            "human_review_reason",
        ):
            if field in case:
                result[field] = case.get(field)

    if result:
        return result

    state = case.get("state")

    result = _dict_value(
        state,
        *keys[number],
    )

    if not result and isinstance(state, dict):
        if number == 1 and isinstance(state.get("agent1_enrichment"), dict):
            return state["agent1_enrichment"]
        if number == 2 and isinstance(state.get("risk_assessment"), dict):
            return state["risk_assessment"]

    if result:
        return result

    return {}


def get_agent_list(
    agent: dict[str, Any],
    *keys: str,
) -> list[Any]:
    for key in keys:
        value = agent.get(key)

        if isinstance(value, list):
            return value

    return []


def agent_completed(
    case: dict[str, Any],
    number: int,
) -> bool:
    result = get_agent_result(
        case,
        number,
    )

    if result:
        return True

    direct_keys = {
        1: (
            "agent1_completed",
            "agent_1_completed",
        ),
        2: (
            "agent2_completed",
            "agent_2_completed",
        ),
        3: (
            "agent3_completed",
            "agent_3_completed",
        ),
    }

    for key in direct_keys[number]:
        if case.get(key) is True:
            return True

    return False


# ============================================================
# API LOADERS
# ============================================================

def load_cases() -> list[dict[str, Any]]:
    try:
        return list_from(
            api.list_cases(
                limit=200,
            )
        )
    except APIError as exc:
        st.error(
            f"Unable to load cases: {exc}"
        )
        return []


def load_case(
    case_id: str,
    force: bool = False,
) -> dict[str, Any] | None:
    if (
        not force
        and case_id in st.session_state.case_cache
    ):
        cached = st.session_state.case_cache[
            case_id
        ]

        if isinstance(cached, dict):
            return cached

    try:
        result = normalize_data(
            api.get_case(case_id)
        )

        if isinstance(result, dict):
            st.session_state.case_cache[
                case_id
            ] = result

            return result

    except APIError as exc:
        cached = (
            st.session_state.case_cache.get(
                case_id
            )
        )

        if cached:
            st.warning(
                "Showing the last available case state."
            )
            return cached

        st.error(
            f"Unable to load case: {exc}"
        )

    return None


def load_applicants(
    search: str | None = None,
) -> list[dict[str, Any]]:
    try:
        applicants = list_from(
            api.list_applicants(limit=200)
        )
    except APIError as exc:
        st.error(f"Unable to load applicants: {exc}")
        return []

    if not search:
        return applicants

    query = search.strip().lower()
    filtered = []
    for applicant in applicants:
        profile = applicant.get("applicant_profile", {})
        if not isinstance(profile, dict):
            profile = {}
        searchable = " ".join([
            str(applicant.get("applicant_id", "")),
            str(applicant.get("name", "")),
            str(profile.get("name", "")),
        ]).lower()
        if query in searchable:
            filtered.append(applicant)
    return filtered


def load_applicant(
    applicant_id_value: str,
) -> dict[str, Any] | None:
    try:
        result = normalize_data(
            api.get_applicant(
                applicant_id_value
            )
        )

        if isinstance(result, dict):
            st.session_state.applicant_cache[
                applicant_id_value
            ] = result

            return result

    except APIError as exc:
        cached = (
            st.session_state
            .applicant_cache
            .get(
                applicant_id_value
            )
        )

        if cached:
            st.warning(
                "Showing the last available applicant data."
            )
            return cached

        st.error(
            f"Unable to load applicant: {exc}"
        )

    return None


def load_documents(
    case_id: str,
) -> list[dict[str, Any]]:
    try:
        return list_from(
            api.list_case_documents(case_id)
        )
    except APIError:
        return []


def load_events(
    case_id: str,
) -> list[dict[str, Any]]:
    try:
        return list_from(
            api.get_events(case_id)
        )
    except APIError:
        return []


def load_reviews(
    case_id: str,
) -> list[dict[str, Any]]:
    try:
        return list_from(
            api.get_reviews(case_id)
        )
    except APIError:
        return []


# ============================================================
# CASE STATUS / ACTIONS
# ============================================================

def action_for_case(
    case: dict[str, Any],
) -> tuple[str, str]:
    status = status_key(
        case.get("status")
        or case.get("processing_status")
    )

    if status in {
        "draft",
        "pending",
    }:
        return (
            "Start Underwriting",
            "start",
        )

    if status in {
        "in-progress",
        "running",
        "processing",
        "agent1",
        "agent2",
        "agent3",
    }:
        return (
            "Processing",
            "running",
        )

    if status in {
        "human-review",
        "review",
        "awaiting-human-review",
        "escalated",
    }:
        return (
            "Human Review",
            "review",
        )

    if status == "sent-back":
        return (
            "Continue Underwriting",
            "continue",
        )

    return (
        "View Assessment",
        "view",
    )


# ============================================================
# UNDERWRITING
# ============================================================

def run_underwriting(
    case_id: str,
) -> None:
    if st.session_state.underwriting_running:
        return

    st.session_state.underwriting_running = True
    st.session_state.case_cache.pop(case_id, None)

    try:
        import time as _time

        with st.status(
            "Underwriting in progress",
            expanded=True,
        ) as status:
            st.write("Starting the LangGraph underwriting workflow...")

            response = api.start_case(case_id)
            data = normalize_data(response)

            if isinstance(data, dict):
                st.session_state.case_cache[case_id] = data

            status.update(
                label="Workflow started — waiting for agents",
                state="running",
                expanded=True,
            )

            # The backend starts the workflow asynchronously. Poll the
            # persisted case state so the UI shows the actual backend result
            # instead of assuming that HTTP 202 means completion.
            terminal = {
                "completed",
                "failed",
                "awaiting-human-review",
                "human-review",
                "escalated",
            }

            progress_bar = st.progress(0.0)
            stage_placeholder = st.empty()
            detail_placeholder = st.empty()

            last_stage = None

            for _ in range(180):
                _time.sleep(1)

                current = normalize_data(
                    api.get_case(case_id)
                )
                if not isinstance(current, dict):
                    continue

                st.session_state.case_cache[case_id] = current

                current_status = status_key(
                    current.get("final_status")
                    or current.get("status")
                    or current.get("processing_status")
                )

                progress = get_progress(current)
                progress_bar.progress(progress)

                current_agent = (
                    current.get("current_agent")
                    or current.get("current_node")
                    or current.get("current_step")
                    or current_status
                )
                stage_label = humanize(current_agent)

                if stage_label != last_stage:
                    stage_placeholder.markdown(
                        f"**Current stage:** {esc(stage_label)}"
                    )
                    last_stage = stage_label

                detail_placeholder.caption(
                    f"Status: {humanize(current_status)}  ·  "
                    f"Progress: {progress * 100:.0f}%"
                )

                if current_status in terminal:
                    break
            else:
                status.update(
                    label="Workflow is taking longer than expected",
                    state="running",
                    expanded=True,
                )
                st.warning(
                    "The backend workflow is still processing after 3 minutes. "
                    "The case remains active; you can refresh the case later to see the final result."
                )

            final_case = normalize_data(
                api.get_case(case_id)
            )

            if isinstance(final_case, dict):
                st.session_state.case_cache[case_id] = final_case
                final_status = status_key(
                    final_case.get("final_status")
                    or final_case.get("status")
                    or final_case.get("processing_status")
                )

                if final_status == "failed":
                    status.update(
                        label="Underwriting workflow failed",
                        state="error",
                        expanded=True,
                    )
                elif final_status in {
                    "awaiting-human-review",
                    "human-review",
                    "escalated",
                }:
                    status.update(
                        label="Human review required",
                        state="complete",
                        expanded=False,
                    )
                else:
                    status.update(
                        label="Underwriting workflow completed",
                        state="complete",
                        expanded=False,
                    )

        st.session_state.selected_case_id = case_id
        st.session_state.workspace_section = "Overview"
        st.session_state.underwriting_running = False
        st.rerun()

    except APIError as exc:
        st.session_state.underwriting_running = False
        st.error(f"Underwriting failed: {exc}")

    except Exception as exc:
        st.session_state.underwriting_running = False
        st.error(f"Unexpected underwriting error: {exc}")


# ============================================================
# SIDEBAR
# ============================================================

def render_sidebar() -> None:
    with st.sidebar:

        st.markdown(
            """
            <div style="
                font-size:23px;
                font-weight:800;
                color:#ffffff;
                line-height:1.1;
            ">
                MedUnderwrite AI
            </div>

            <div style="
                font-size:12px;
                color:#9aaac0;
                margin-top:5px;
                margin-bottom:25px;
            ">
                Medical Underwriting Workstation
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.caption("WORKSPACE")

        navigation = [
            ("Dashboard", "dashboard"),
            ("All Cases", "cases"),
            ("Human Review", "review"),
        ]

        for label, page in navigation:
            if st.button(
                label,
                key=f"nav_{page}",
                use_container_width=True,
            ):
                st.session_state.page = page
                st.rerun()

        st.caption("REFERENCE")

        if st.button(
            "Applicants",
            key="nav_applicants",
            use_container_width=True,
        ):
            st.session_state.page = "applicants"
            st.rerun()

        st.caption("SYSTEM")

        if st.button(
            "System Status",
            key="nav_system",
            use_container_width=True,
        ):
            st.session_state.page = "system"
            st.rerun()


# ============================================================
# DASHBOARD
# ============================================================

def render_dashboard() -> None:
    page_header(
        "Underwriting Dashboard",
        "Decision-focused overview of the medical underwriting workload.",
    )

    cases = load_cases()

    status_counts: dict[str, int] = {}

    for case in cases:
        current = status_key(
            case.get("status")
            or case.get("processing_status")
        )

        status_counts[current] = (
            status_counts.get(current, 0) + 1
        )

    metrics = [
        (
            "Total Cases",
            len(cases),
        ),
        (
            "Pending",
            status_counts.get("draft", 0)
            + status_counts.get("pending", 0),
        ),
        (
            "In Progress",
            sum(
                status_counts.get(
                    value,
                    0,
                )
                for value in (
                    "in-progress",
                    "running",
                    "processing",
                    "agent1",
                    "agent2",
                    "agent3",
                )
            ),
        ),
        (
            "Human Review",
            status_counts.get(
                "human-review",
                0,
            )
            + status_counts.get(
                "review",
                0,
            ),
        ),
        (
            "Completed",
            status_counts.get(
                "completed",
                0,
            ),
        ),
    ]

    columns = st.columns(5)

    for column, (
        label,
        value,
    ) in zip(
        columns,
        metrics,
    ):
        with column:
            st.metric(
                label,
                value,
            )

    st.divider()

    section_title(
        "Cases Requiring Attention",
        "Prioritize submissions that need an underwriting action.",
    )

    attention = [
        case
        for case in cases
        if status_key(
            case.get("status")
            or case.get("processing_status")
        )
        in {
            "draft",
            "pending",
            "human-review",
            "review",
            "sent-back",
            "failed",
        }
    ]

    if not attention:
        render_empty(
            "Queue Clear",
            "There are no cases currently waiting for action.",
        )
    else:
        for case in attention[:8]:
            render_case_row(
                case,
                key_suffix="attention",
            )

    st.divider()

    section_title(
        "Recent Cases",
        "Latest underwriting submissions.",
    )

    for case in cases[:8]:
        render_case_row(
            case,
            key_suffix="recent",
        )


# ============================================================
# CASE ROW
# ============================================================

def render_case_row(
    case: dict[str, Any],
    key_suffix: str = "cases",
) -> None:
    case_id = str(
        case.get("case_id")
        or "—"
    )

    name = applicant_name(case)
    app_id = applicant_id(case)

    current_status = status_key(
        case.get("status")
        or case.get("processing_status")
    )

    action_label, action_kind = (
        action_for_case(case)
    )

    columns = st.columns(
        [
            1.1,
            1.8,
            2.5,
            1.3,
            1.25,
        ]
    )

    with columns[0]:
        st.caption("CASE")
        st.markdown(
            f"**{esc(case_id)}**",
            unsafe_allow_html=True,
        )

    with columns[1]:
        st.caption("APPLICANT")
        st.markdown(
            f"**{esc(name)}**",
            unsafe_allow_html=True,
        )

        if app_id:
            st.caption(app_id)

    with columns[2]:
        st.caption("PRODUCT")
        st.write(
            product(case)
        )

    with columns[3]:
        st.caption("STATUS")
        status_badge(
            current_status,
            status_label(current_status),
        )

    with columns[4]:

        if action_kind == "start":

            if st.button(
                "Underwrite",
                key=f"underwrite_{case_id}_{key_suffix}",
                use_container_width=True,
                disabled=st.session_state.underwriting_running,
            ):
                run_underwriting(
                    case_id
                )

        elif action_kind == "running":

            st.button(
                "Processing...",
                key=f"processing_{case_id}_{key_suffix}",
                use_container_width=True,
                disabled=True,
            )

        elif action_kind == "review":

            if st.button(
                "Review",
                key=f"review_{case_id}_{key_suffix}",
                use_container_width=True,
            ):
                open_case(
                    case_id,
                    "Human Review",
                )

        elif action_kind == "continue":

            if st.button(
                "Continue",
                key=f"continue_{case_id}_{key_suffix}",
                use_container_width=True,
            ):
                open_case(
                    case_id,
                    "Overview",
                )

        else:

            if st.button(
                "View Case",
                key=f"view_{case_id}_{key_suffix}",
                use_container_width=True,
            ):
                open_case(
                    case_id,
                    "Overview",
                )

    st.divider()


# ============================================================
# ALL CASES
# ============================================================

def render_cases() -> None:
    page_header(
        "All Cases",
        "Search and manage underwriting submissions.",
    )

    cases = load_cases()

    columns = st.columns(
        [2.5, 1.2, 1]
    )

    with columns[0]:
        query = st.text_input(
            "Search cases",
            placeholder=(
                "Case ID, Applicant ID, or applicant name"
            ),
            label_visibility="collapsed",
        ).strip().lower()

    with columns[1]:
        selected_status = st.selectbox(
            "Status",
            [
                "All",
                "Draft",
                "In Progress",
                "Human Review",
                "Completed",
                "Failed",
                "Sent Back",
            ],
            label_visibility="collapsed",
        )

    with columns[2]:
        if st.button(
            "Refresh",
            use_container_width=True,
        ):
            st.session_state.case_cache.clear()
            st.rerun()

    filtered: list[dict[str, Any]] = []

    for case in cases:

        searchable = " ".join(
            [
                str(
                    case.get(
                        "case_id",
                        "",
                    )
                ),
                applicant_id(case),
                applicant_name(case),
                product(case),
            ]
        ).lower()

        if query and query not in searchable:
            continue

        current = status_key(
            case.get("status")
            or case.get("processing_status")
        )

        if selected_status != "All":

            expected = status_key(
                selected_status
            )

            if selected_status == "In Progress":
                if current not in {
                    "in-progress",
                    "running",
                    "processing",
                    "agent1",
                    "agent2",
                    "agent3",
                }:
                    continue

            elif selected_status == "Human Review":
                if current not in {
                    "human-review",
                    "review",
                    "awaiting-human-review",
                    "escalated",
                }:
                    continue

            elif current != expected:
                continue

        filtered.append(case)

    if not filtered:
        render_empty(
            "No Matching Cases",
            "Try a different applicant, case ID, or status filter.",
        )
        return

    st.caption(
        f"{len(filtered)} case(s)"
    )

    for case in filtered:
        render_case_row(case)


# ============================================================
# APPLICANTS
# ============================================================

def render_applicants() -> None:
    page_header(
        "Applicants",
        "Reference view for applicants and their underwriting cases.",
    )

    query = st.text_input(
        "Search applicants",
        placeholder="Applicant ID or name",
        label_visibility="collapsed",
    ).strip()

    applicants = load_applicants(
        search=query or None
    )

    if not applicants:
        render_empty(
            "No Applicants",
            "No applicants matched the current search.",
        )
        return

    for applicant in applicants:

        profile = applicant.get(
            "applicant_profile"
        )

        if not isinstance(
            profile,
            dict,
        ):
            profile = applicant

        app_id = str(
            applicant.get(
                "applicant_id"
            )
            or profile.get(
                "applicant_id"
            )
            or "—"
        )

        name = str(
            profile.get(
                "name"
            )
            or applicant.get(
                "name"
            )
            or "Unknown"
        )

        age = profile.get(
            "age"
        )

        cases = applicant.get(
            "cases"
        )

        if not isinstance(
            cases,
            list,
        ):
            cases = []

        columns = st.columns(
            [
                1.3,
                2.2,
                1,
                1,
            ]
        )

        with columns[0]:
            st.caption("APPLICANT ID")
            st.markdown(
                f"**{esc(app_id)}**"
            )

        with columns[1]:
            st.caption("NAME")
            st.markdown(
                f"**{esc(name)}**"
            )

        with columns[2]:
            st.caption("AGE")
            st.write(
                text(age)
            )

        with columns[3]:
            if st.button(
                "Open Profile",
                key=f"applicant_{app_id}",
                use_container_width=True,
            ):
                open_applicant(app_id)

        st.divider()


# ============================================================
# APPLICANT DETAIL
# ============================================================

def render_applicant_detail() -> None:
    app_id = st.session_state.selected_applicant_id

    if not app_id:
        st.warning(
            "No applicant selected."
        )
        return

    applicant = load_applicant(
        app_id
    )

    if not applicant:
        return

    profile = applicant.get(
        "applicant_profile"
    )

    if not isinstance(
        profile,
        dict,
    ):
        profile = applicant

    name = str(
        profile.get(
            "name"
        )
        or "Applicant"
    )

    page_header(
        "Applicant Profile",
        f"{name} · {app_id}",
    )

    top = st.columns(
        [2.2, 1, 1, 1]
    )

    with top[0]:
        st.markdown(
            f"### {esc(name)}"
        )

    with top[1]:
        st.caption("APPLICANT ID")
        st.write(
            app_id
        )

    with top[2]:
        st.caption("AGE")
        st.write(
            text(
                profile.get("age")
            )
        )

    with top[3]:
        st.caption("SOURCE")
        st.write(
            humanize(
                applicant.get(
                    "source"
                )
                or profile.get(
                    "source"
                )
            )
        )

    st.divider()

    render_applicant_medical_profile(
        profile
    )

    render_treatment_history(
        profile
    )

    render_claim_history(
        profile
    )

    render_existing_policy(
        profile
    )

    render_applicant_cases(
        applicant
    )


# ============================================================
# APPLICANT MEDICAL PROFILE
# ============================================================

def render_applicant_medical_profile(
    profile: dict[str, Any],
) -> None:
    section_title(
        "Medical Profile",
        "Declared medical conditions and current medications.",
    )

    columns = st.columns(2)

    conditions = profile.get(
        "medical_conditions"
    )

    if not isinstance(
        conditions,
        list,
    ):
        conditions = []

    medications = profile.get(
        "medications"
    )

    if not isinstance(
        medications,
        list,
    ):
        medications = []

    with columns[0]:

        st.markdown(
            "#### Medical Conditions"
        )

        if not conditions:
            st.caption(
                "No medical conditions declared."
            )
        else:

            for index, condition in enumerate(
                conditions,
                start=1,
            ):

                if isinstance(
                    condition,
                    dict,
                ):

                    condition_name = (
                        condition.get(
                            "condition"
                        )
                        or condition.get(
                            "name"
                        )
                        or "Condition"
                    )

                    year = condition.get(
                        "year_diagnosed"
                    )

                    condition_name = clean_condition(
                        condition_name
                    )

                    title = (
                        f"{condition_name}"
                    )

                    if year:
                        title += (
                            f" · {year}"
                        )

                    st.markdown(
                        f"**{esc(title)}**"
                    )

                    status = condition.get(
                        "status"
                    )

                    if status:
                        st.caption(
                            clean_condition(
                                status
                            )
                        )

                else:
                    st.markdown(
                        f"**{esc(str(condition))}**"
                    )

                if index < len(conditions):
                    st.write("")

    with columns[1]:

        st.markdown(
            "#### Current Medication"
        )

        if not medications:
            st.caption(
                "No medications declared."
            )
        else:

            for medication in medications:

                if isinstance(
                    medication,
                    dict,
                ):

                    name = (
                        medication.get(
                            "name"
                        )
                        or medication.get(
                            "medication"
                        )
                        or "Medication"
                    )

                    details = (
                        medication.get(
                            "details"
                        )
                        or medication.get(
                            "dosage"
                        )
                        or medication.get(
                            "instructions"
                        )
                    )

                    if name and details:
                        st.markdown(
                            f"**{esc(name)}**"
                        )
                        st.caption(
                            clean_medication_detail(
                                details
                            )
                        )

                    elif name:
                        st.markdown(
                            f"**{esc(name)}**"
                        )

                else:
                    st.markdown(
                        f"**{esc(str(medication))}**"
                    )


def clean_condition(
    value: Any,
) -> str:
    value = str(
        value or ""
    ).strip()

    if not value:
        return "—"

    noise = [
        "Year diagnosed",
        "Status (as declared)",
    ]

    for item in noise:
        value = value.replace(
            item,
            "",
        )

    value = " ".join(
        value.split()
    )

    return value.strip()


def clean_medication_detail(
    value: Any,
) -> str:
    value = str(
        value or ""
    ).strip()

    if not value:
        return ""

    return " ".join(
        value.split()
    )


# ============================================================
# TREATMENT HISTORY
# ============================================================

def render_treatment_history(
    profile: dict[str, Any],
) -> None:
    hospitalizations = profile.get(
        "hospitalizations"
    )

    if not isinstance(
        hospitalizations,
        list,
    ):
        hospitalizations = []

    section_title(
        "Treatment History",
        "Hospitalization and day-care treatment history.",
    )

    if not hospitalizations:
        st.caption(
            "No hospitalization or treatment history declared."
        )
        return

    for index, item in enumerate(
        hospitalizations,
        start=1,
    ):

        details = (
            item.get("details")
            if isinstance(
                item,
                dict,
            )
            else item
        )

        columns = st.columns(
            [0.45, 5.5]
        )

        with columns[0]:
            st.caption(
                f"{index:02d}"
            )

        with columns[1]:
            st.write(
                clean_medication_detail(
                    details
                )
            )


# ============================================================
# CLAIM HISTORY
# ============================================================

def render_claim_history(
    profile: dict[str, Any],
) -> None:
    claims = profile.get(
        "claims"
    )

    if not isinstance(
        claims,
        list,
    ):
        claims = []

    section_title(
        "Claims History",
        "Historical insurance claims declared in the submission.",
    )

    if not claims:
        st.caption(
            "No historical claims declared."
        )
        return

    st.caption(
        f"{len(claims)} historical claim(s) declared"
    )

    for claim in claims:

        if isinstance(
            claim,
            dict,
        ):
            claim_id = (
                claim.get(
                    "claim_id"
                )
                or claim.get(
                    "id"
                )
                or "Historical claim"
            )

            status = humanize(
                claim.get(
                    "status"
                )
                or "Historical"
            )

            date = (
                claim.get(
                    "date"
                )
                or claim.get(
                    "claim_date"
                )
            )

            amount = (
                claim.get(
                    "amount"
                )
                or claim.get(
                    "paid_amount"
                )
            )

            columns = st.columns(
                [
                    1.5,
                    1.5,
                    1.5,
                    1.5,
                ]
            )

            with columns[0]:
                st.caption("CLAIM")
                st.write(
                    claim_id
                )

            with columns[1]:
                st.caption("STATUS")
                st.write(
                    status
                )

            with columns[2]:
                st.caption("DATE")
                st.write(
                    date or "—"
                )

            with columns[3]:
                st.caption("AMOUNT")
                st.write(
                    format_currency(
                        amount
                    )
                    if amount
                    else "—"
                )

        else:
            st.write(
                str(claim)
            )

        st.divider()


# ============================================================
# EXISTING POLICY
# ============================================================

def render_existing_policy(
    profile: dict[str, Any],
) -> None:
    policy = profile.get(
        "existing_policy"
    )

    section_title(
        "Existing Policy",
        "Current insurance policy information.",
    )

    if not isinstance(
        policy,
        dict,
    ) or not policy:
        st.caption(
            "No existing policy declared."
        )
        return

    columns = st.columns(
        [
            1.5,
            1.5,
            2,
            2,
        ]
    )

    fields = [
        (
            "POLICY ID",
            policy.get(
                "policy_id"
            ),
        ),
        (
            "STATUS",
            humanize(
                policy.get(
                    "status"
                )
            ),
        ),
        (
            "TYPE",
            policy.get(
                "type"
            ),
        ),
        (
            "COVERAGE LIMIT",
            format_currency(
                policy.get(
                    "coverage_limit"
                )
            ),
        ),
    ]

    for column, (
        label,
        value,
    ) in zip(
        columns,
        fields,
    ):
        with column:
            st.caption(label)
            st.write(
                text(value)
            )


# ============================================================
# APPLICANT CASES
# ============================================================

def render_applicant_cases(
    applicant: dict[str, Any],
) -> None:
    cases = applicant.get(
        "cases"
    )

    if not isinstance(
        cases,
        list,
    ):
        cases = []

    section_title(
        "Underwriting Cases",
        "Cases associated with this applicant.",
    )

    if not cases:
        st.caption(
            "No underwriting cases found."
        )
        return

    for case in cases:

        case_id = str(
            case.get(
                "case_id"
            )
            or "—"
        )

        status = status_key(
            case.get(
                "status"
            )
        )

        columns = st.columns(
            [
                1.2,
                1.2,
                2,
                2,
                1.2,
                1.2,
            ]
        )

        with columns[0]:
            st.caption("CASE")
            st.markdown(
                f"**{esc(case_id)}**"
            )

        with columns[1]:
            st.caption("APPLICANT")
            st.write(
                applicant.get(
                    "applicant_id",
                    "—",
                )
            )

        with columns[2]:
            st.caption("APPLICANT NAME")
            st.write(
                applicant_name(case)
            )

        with columns[3]:
            st.caption("PRODUCT")
            st.write(
                product(case)
            )

        with columns[4]:
            st.caption("STATUS")
            status_badge(
                status,
                status_label(status),
            )

        with columns[5]:
            if st.button(
                "Open",
                key=f"app_case_{case_id}",
                use_container_width=True,
            ):
                open_case(
                    case_id
                )

        st.divider()


# ============================================================
# CASE HEADER
# ============================================================

def render_case_header(
    case: dict[str, Any],
) -> None:
    case_id = str(
        case.get(
            "case_id"
        )
        or "—"
    )

    name = applicant_name(
        case
    )

    status = status_key(
        case.get("status")
        or case.get("processing_status")
    )

    score = overall_risk(
        case
    )

    st.markdown(
        f"## {esc(case_id)}"
    )

    st.caption(
        f"{esc(name)} · {status_label(status)}"
    )

    columns = st.columns(
        [
            1.5,
            2.4,
            1.5,
            1.5,
            1.3,
        ]
    )

    submission = submission_from_case(
        case
    )

    with columns[0]:
        st.caption("APPLICANT")
        st.markdown(
            f"**{esc(name)}**"
        )

    with columns[1]:
        st.caption("PRODUCT")
        st.write(
            submission.get(
                "product",
                "Medical Insurance",
            )
        )

    with columns[2]:
        st.caption("SUM INSURED")
        st.write(
            format_currency(
                submission.get(
                    "sum_insured"
                )
            )
        )

    with columns[3]:
        st.caption("RISK")
        if score is None:
            st.write("Pending")
        else:
            st.markdown(
                f"**{risk_display(score)} · "
                f"{risk_band(score)}**"
            )

    with columns[4]:
        st.caption("STATUS")
        status_badge(
            status,
            status_label(status),
        )


# ============================================================
# CASE WORKSPACE NAVIGATION
# ============================================================

WORKSPACE_SECTIONS = [
    "Overview",
    "Applicant",
    "Submission",
    "Evidence",
    "Agent 1",
    "Agent 2",
    "Agent 3",
    "Decision",
    "Workflow",
    "Human Review",
]


def render_workspace_navigation() -> None:
    st.markdown(
        "### Case Workspace"
    )

    selected = st.session_state.workspace_section

    columns = st.columns(
        4
    )

    for index, section in enumerate(
        WORKSPACE_SECTIONS
    ):

        column = columns[
            index % 4
        ]

        with column:

            label = (
                f"● {section}"
                if section == selected
                else section
            )

            if st.button(
                label,
                key=f"workspace_{index}",
                use_container_width=True,
            ):
                st.session_state.workspace_section = (
                    section
                )
                st.rerun()

    st.divider()


# ============================================================
# CASE WORKSPACE
# ============================================================

def render_case_workspace() -> None:
    case_id = st.session_state.selected_case_id

    if not case_id:
        st.warning(
            "No case selected."
        )
        return

    case = load_case(
        case_id,
        force=True,
    )

    if not case:
        return

    render_case_header(
        case
    )

    current_status = status_key(
        case.get("status")
        or case.get("processing_status")
    )

    if st.session_state.underwriting_running:
        st.info(
            "Underwriting is currently running. "
            "The action is disabled until the workflow finishes."
        )

    render_case_action_bar(
        case
    )

    render_workspace_navigation()

    section = st.session_state.workspace_section

    if section == "Overview":
        render_case_overview(case)

    elif section == "Applicant":
        render_case_applicant(case)

    elif section == "Submission":
        render_case_submission(case)

    elif section == "Evidence":
        render_case_evidence(case)

    elif section == "Agent 1":
        render_agent_section(
            case,
            1,
        )

    elif section == "Agent 2":
        render_agent_section(
            case,
            2,
        )

    elif section == "Agent 3":
        render_agent3_section(case)

    elif section == "Decision":
        render_decision_section(case)

    elif section == "Workflow":
        render_workflow_section(case)

    elif section == "Human Review":
        render_human_review(case)


# ============================================================
# CASE ACTION BAR
# ============================================================

def render_case_action_bar(
    case: dict[str, Any],
) -> None:
    status = status_key(
        case.get("status")
        or case.get("processing_status")
    )

    st.markdown(
        "### Case Actions"
    )

    if status in {
        "draft",
        "pending",
    }:

        st.info(
            "This case has not been underwritten yet."
        )

        if st.button(
            "▶ Start Underwriting",
            type="primary",
            use_container_width=False,
            disabled=st.session_state.underwriting_running,
        ):
            run_underwriting(
                case.get("case_id")
            )

    elif status in {
        "in-progress",
        "running",
        "processing",
        "agent1",
        "agent2",
        "agent3",
    }:

        st.warning(
            "Underwriting is in progress. "
            "The final assessment will appear when the workflow completes."
        )

        st.progress(
            get_progress(
                case
            )
        )

        st.button(
            "Underwriting in Progress...",
            disabled=True,
        )

    elif status in {
        "human-review",
        "review",
        "awaiting-human-review",
        "escalated",
    }:

        st.warning(
            "This case requires human review before final completion."
        )

        if st.button(
            "Open Human Review",
            type="primary",
        ):
            st.session_state.workspace_section = (
                "Human Review"
            )
            st.rerun()

    elif status == "sent-back":

        st.warning(
            "This case was sent back for additional underwriting work."
        )

        if st.button(
            "Continue Underwriting",
            type="primary",
        ):
            run_underwriting(
                case.get("case_id")
            )

    elif status == "completed":

        st.success(
            "Underwriting completed. "
            "The assessment below contains the generated risk and decision package."
        )

    elif status == "failed":

        st.error(
            "The underwriting workflow failed. "
            "Review the workflow and audit information below."
        )


def get_progress(
    case: dict[str, Any],
) -> float:
    explicit = case.get(
        "progress_pct"
    )

    if explicit is not None:
        try:
            return max(
                0.0,
                min(
                    float(explicit) / 100,
                    1.0,
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

    status = status_key(
        case.get(
            "status"
        )
        or case.get(
            "processing_status"
        )
    )

    values = {
        "draft": 0.0,
        "pending": 0.05,
        "agent1": 0.30,
        "in-progress": 0.45,
        "running": 0.50,
        "agent2": 0.60,
        "agent3": 0.80,
        "human-review": 0.90,
        "review": 0.90,
        "awaiting-human-review": 0.90,
        "escalated": 0.95,
        "completed": 1.0,
    }

    return values.get(
        status,
        0.0,
    )


# ============================================================
# CASE OVERVIEW
# ============================================================

def render_case_overview(
    case: dict[str, Any],
) -> None:
    section_title(
        "Case Overview",
        "The information an underwriter needs first.",
    )

    submission = submission_from_case(
        case
    )

    score = overall_risk(
        case
    )

    # Compact case summary instead of large metric cards.
    columns = st.columns(
        [
            1.4,
            2,
            1.4,
            1.2,
        ]
    )

    with columns[0]:
        st.caption("APPLICANT")
        st.markdown(
            f"### {esc(applicant_name(case))}"
        )

    with columns[1]:
        st.caption("PRODUCT")
        st.markdown(
            f"### {esc(product(case))}"
        )

    with columns[2]:
        st.caption("SUM INSURED")
        st.markdown(
            f"### {esc(format_currency(submission.get('sum_insured')))}"
        )

    with columns[3]:
        st.caption("RISK")
        if score is None:
            st.markdown(
                "### Pending"
            )
        else:
            st.markdown(
                f"### {risk_display(score)}"
            )
            st.caption(
                risk_band(score)
            )

    if score is None:
        st.info(
            "Risk and recommendation values will appear after underwriting."
        )
        return

    st.divider()

    render_decision_snapshot(
        case
    )

    st.divider()

    render_recommendation_summary(
        case
    )

    st.divider()

    render_result_highlights(
        case
    )


# ============================================================
# DECISION SNAPSHOT
# ============================================================

def render_decision_snapshot(
    case: dict[str, Any],
) -> None:
    section_title(
        "Decision Snapshot",
        "Risk components generated by Agent 2.",
    )

    fields = [
        (
            "Overall Risk",
            risk_value(
                case,
                "overall_risk_score",
            ),
        ),
        (
            "Medical Risk",
            risk_value(
                case,
                "medical_risk_score",
            ),
        ),
        (
            "Claims Risk",
            risk_value(
                case,
                "claims_risk_score",
            ),
        ),
        (
            "Coverage Gap Risk",
            risk_value(
                case,
                "coverage_gap_score",
            ),
        ),
    ]

    columns = st.columns(4)

    for column, (
        label,
        value,
    ) in zip(
        columns,
        fields,
    ):
        with column:
            st.caption(
                label.upper()
            )

            if value is None:
                st.markdown(
                    "### —"
                )
            else:
                st.markdown(
                    f"### {text(value)}"
                )


# ============================================================
# RECOMMENDATION
# ============================================================

def render_recommendation_summary(
    case: dict[str, Any],
) -> None:
    section_title(
        "Recommendation & Decision",
        "Automated underwriting recommendation and final decision.",
    )

    columns = st.columns(2)

    with columns[0]:

        st.caption(
            "AUTOMATED RECOMMENDATION"
        )

        value = recommendation(
            case
        )

        if value == "Pending":
            st.info(
                "Pending underwriting."
            )
        else:
            st.markdown(
                f"## {esc(value)}"
            )

        loading = extract_loading(
            case
        )

        if loading is not None:
            st.caption(
                f"Pricing loading: {loading}"
            )

    with columns[1]:

        st.caption(
            "FINAL DECISION"
        )

        value = decision(
            case
        )

        if value == "Pending":
            st.info(
                "Pending finalization."
            )
        else:
            st.markdown(
                f"## {esc(value)}"
            )

        confidence = extract_confidence(
            case
        )

        if confidence is not None:
            st.caption(
                f"Confidence: {confidence}"
            )


def extract_loading(
    case: dict[str, Any],
) -> str | None:
    candidates = [
        case.get("loading"),
        case.get("loading_pct"),
        case.get("agent2_loading"),
        case.get("loading_percentage"),
        (case.get("pricing_result") or {}).get("loading_percentage") if isinstance(case.get("pricing_result"), dict) else None,
        risk_assessment(case).get(
            "loading"
        ),
        risk_assessment(case).get(
            "loading_pct"
        ),
        get_agent_result(
            case,
            2,
        ).get(
            "loading"
        ),
        get_agent_result(
            case,
            2,
        ).get(
            "loading_pct"
        ),
    ]

    for value in candidates:
        if value is None:
            continue

        try:
            numeric = float(value)

            if numeric <= 1:
                numeric *= 100

            return f"{numeric:.0f}%"

        except (
            TypeError,
            ValueError,
        ):
            return str(value)

    return None


def extract_confidence(
    case: dict[str, Any],
) -> str | None:
    candidates = [
        case.get("final_confidence"),
        case.get("confidence"),
        case.get("agent2_confidence"),
        risk_assessment(case).get("confidence"),
        get_agent_result(case, 2).get("confidence"),
    ]

    for value in candidates:
        if value is None:
            continue

        try:
            numeric = float(value)

            if numeric <= 1:
                numeric *= 100

            return f"{numeric:.0f}%"

        except (
            TypeError,
            ValueError,
        ):
            return str(value)

    return None


# ============================================================
# RESULT HIGHLIGHTS
# ============================================================

def render_result_highlights(
    case: dict[str, Any],
) -> None:
    section_title(
        "Underwriting Highlights",
        "The most important findings from the completed assessment.",
    )

    risk = risk_assessment(
        case
    )

    factors = get_list(
        risk,
        "risk_factors",
    )

    if not factors:
        factors = get_list(
            get_agent_result(
                case,
                2,
            ),
            "risk_factors",
        )

    gaps = (
        case.get(
            "coverage_gaps"
        )
        or risk.get(
            "coverage_gaps"
        )
        or get_agent_result(
            case,
            2,
        ).get(
            "coverage_gaps"
        )
        or []
    )

    if not isinstance(
        gaps,
        list,
    ):
        gaps = []

    columns = st.columns(2)

    with columns[0]:

        st.markdown(
            "#### Key Risk Factors"
        )

        if not factors:
            st.caption(
                "No structured risk factors were returned."
            )
        else:

            for factor in factors[:8]:

                if isinstance(
                    factor,
                    dict,
                ):
                    description = (
                        factor.get(
                            "factor"
                        )
                        or factor.get(
                            "description"
                        )
                        or factor.get(
                            "reason"
                        )
                        or str(factor)
                    )
                else:
                    description = str(
                        factor
                    )

                st.write(
                    f"• {description}"
                )

    with columns[1]:

        st.markdown(
            "#### Coverage Gaps"
        )

        if not gaps:
            st.caption(
                "No coverage gaps identified."
            )
        else:

            for gap in gaps[:8]:

                if isinstance(
                    gap,
                    dict,
                ):
                    description = (
                        gap.get(
                            "gap"
                        )
                        or gap.get(
                            "description"
                        )
                        or "Coverage gap"
                    )

                    severity = gap.get(
                        "severity"
                    )

                    if severity:
                        st.write(
                            f"• {description} "
                            f"({humanize(severity)})"
                        )
                    else:
                        st.write(
                            f"• {description}"
                        )
                else:
                    st.write(
                        f"• {gap}"
                    )


# ============================================================
# CASE APPLICANT
# ============================================================

def render_case_applicant(
    case: dict[str, Any],
) -> None:
    section_title(
        "Applicant",
        "Applicant medical and historical information used during underwriting.",
    )

    profile = profile_from_case(
        case
    )

    if not profile:
        render_empty(
            "Applicant Data Unavailable",
            "The case does not currently contain applicant profile information.",
        )
        return

    applicant_card(
        {
            "applicant_profile": profile,
            "applicant_id": applicant_id(case),
            "source": profile.get(
                "source"
            ),
            "cases": [],
        }
    )


# ============================================================
# SUBMISSION
# ============================================================

def render_case_submission(
    case: dict[str, Any],
) -> None:
    section_title(
        "Submission",
        "The underwriting request submitted for this case.",
    )

    submission = submission_from_case(
        case
    )

    if not submission:
        render_empty(
            "Submission Unavailable",
            "No underwriting submission is attached to this case.",
        )
        return

    fields = [
        (
            "Product",
            submission.get(
                "product"
            ),
        ),
        (
            "Policy Type",
            submission.get(
                "policy_type"
            ),
        ),
        (
            "Sum Insured",
            format_currency(
                submission.get(
                    "sum_insured"
                )
            ),
        ),
        (
            "Term",
            (
                f"{submission.get('term_years')} year(s)"
                if submission.get(
                    "term_years"
                )
                else "—"
            ),
        ),
        (
            "Requested Start",
            submission.get(
                "requested_start_date"
            ),
        ),
        (
            "Jurisdiction",
            submission.get(
                "jurisdiction"
            ),
        ),
        (
            "Insurer",
            submission.get(
                "insurer"
            ),
        ),
    ]

    for start in range(
        0,
        len(fields),
        3,
    ):

        row = fields[
            start:start + 3
        ]

        columns = st.columns(
            len(row)
        )

        for column, (
            label,
            value,
        ) in zip(
            columns,
            row,
        ):
            with column:
                st.caption(
                    label.upper()
                )
                st.write(
                    text(value)
                )

        st.divider()


# ============================================================
# EVIDENCE
# ============================================================

def render_case_evidence(
    case: dict[str, Any],
) -> None:
    section_title(
        "Evidence",
        "Applicant documents and evidence used to support the underwriting decision.",
    )

    case_id = str(
        case.get("case_id") or ""
    )

    documents = load_documents(case_id)

    evidence = case.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}

    backend_evidence = {
        "medical_evidence": case.get("medical_evidence", []),
        "claims_evidence": case.get("claims_evidence", []),
        "policy_evidence": case.get("policy_evidence", []),
        "regulatory_evidence": case.get("regulatory_evidence", []),
        "underwriting_evidence": case.get("underwriting_evidence", []),
        "medical_knowledge": case.get("medical_knowledge", []),
        "coverage_gaps": case.get("coverage_gaps", []),
    }

    for key, value in backend_evidence.items():
        if isinstance(value, list) and value:
            evidence.setdefault(key, value)

    if evidence:
        evidence_availability(evidence)

    if documents:
        st.markdown("#### Case Documents")
        for document in documents:
            filename = (
                document.get("filename")
                or document.get("name")
                or "Document"
            )
            document_type = humanize(
                document.get("document_type")
                or document.get("type")
                or "Other"
            )
            status = humanize(
                document.get("evidence_status")
                or "Provided"
            )

            columns = st.columns([3, 1.5, 1.5])
            with columns[0]:
                st.markdown(f"**{esc(filename)}**")
            with columns[1]:
                st.caption(document_type)
            with columns[2]:
                st.caption(status)

        st.divider()

    if evidence:
        st.markdown("#### Evidence Reader")
        st.caption(
            "Evidence is grouped by source document. Retrieval chunks are "
            "combined and hidden behind the full-evidence reader."
        )

        scope_map = {
            "regulatory_evidence": "regulatory",
            "medical_knowledge": "knowledge",
            "underwriting_knowledge_evidence": "knowledge",
            "underwriting_evidence": "applicant",
        }

        for key, value in evidence.items():
            if not isinstance(value, list) or not value:
                continue
            if key == "coverage_gaps":
                continue

            evidence_section(
                humanize(key),
                value,
                scope=scope_map.get(key, "applicant"),
            )

    if not documents and not evidence:
        render_empty(
            "No Evidence Available",
            "No applicant-specific evidence is currently attached to this case.",
        )


# ============================================================
# AGENT 1
# ============================================================

def render_agent_section(
    case: dict[str, Any],
    number: int,
) -> None:
    titles = {
        1: (
            "Agent 1 · Evidence & Investigation",
            "Evidence retrieval, medical context, claims context, regulatory context, and underwriting enrichment.",
        ),
        2: (
            "Agent 2 · Risk Assessment",
            "Deterministic medical, claims, coverage-gap, pricing, and recommendation assessment.",
        ),
    }

    title, subtitle = titles[number]

    section_title(
        title,
        subtitle,
    )

    result = get_agent_result(
        case,
        number,
    )

    if not result and not agent_completed(
        case,
        number,
    ):

        st.info(
            f"Agent {number} has not produced a result yet."
        )
        return

    if number == 1:
        render_agent1_result(
            result
        )
    else:
        render_agent2_result(
            case,
            result,
        )

    metrics = (
        result.get("metrics")
        or result.get("agent_metrics")
        or {}
    )
    if metrics:
        st.divider()
        agent_metrics(
            metrics,
            f"Agent {number}",
        )


# ============================================================
# AGENT 1 RESULT
# ============================================================

def render_agent1_result(
    result: dict[str, Any],
) -> None:
    if not result:
        st.info(
            "Agent 1 completed without a structured result payload."
        )
        return

    counts = []

    evidence = (
        result.get(
            "evidence_summary"
        )
        or result.get(
            "evidence"
        )
        or {}
    )

    if isinstance(
        evidence,
        dict,
    ):

        for key, value in evidence.items():

            if isinstance(
                value,
                list,
            ):

                counts.append(
                    (
                        humanize(key),
                        len(value),
                    )
                )

    if counts:

        columns = st.columns(
            min(
                len(counts),
                4,
            )
        )

        for column, (
            label,
            value,
        ) in zip(
            columns,
            counts[:4],
        ):
            with column:
                st.metric(
                    label,
                    value,
                )

    findings = (
        result.get(
            "findings"
        )
        or result.get(
            "summary"
        )
        or result.get(
            "analysis"
        )
    )

    if findings:
        st.markdown(
            "#### Investigation Summary"
        )
        st.write(
            findings
        )

    if evidence:

        st.markdown(
            "#### Evidence Retrieved"
        )

        for key, value in evidence.items():

            if not isinstance(
                value,
                list,
            ) or not value:
                continue

            with st.expander(
                humanize(key),
                expanded=False,
            ):
                for item in value[:20]:

                    if isinstance(
                        item,
                        dict,
                    ):
                        st.json(
                            item
                        )
                    else:
                        st.write(
                            item
                        )


# ============================================================
# AGENT 2 RESULT
# ============================================================

def render_agent2_result(
    case: dict[str, Any],
    result: dict[str, Any],
) -> None:

    values = [
        (
            "Overall Risk",
            risk_value(
                case,
                "overall_risk_score",
            ),
        ),
        (
            "Medical Risk",
            risk_value(
                case,
                "medical_risk_score",
            ),
        ),
        (
            "Claims Risk",
            risk_value(
                case,
                "claims_risk_score",
            ),
        ),
        (
            "Coverage Gap Risk",
            risk_value(
                case,
                "coverage_gap_score",
            ),
        ),
    ]

    columns = st.columns(4)

    for column, (
        label,
        value,
    ) in zip(
        columns,
        values,
    ):
        with column:
            st.caption(
                label.upper()
            )
            st.markdown(
                f"### {text(value)}"
            )

    st.divider()

    columns = st.columns(3)

    with columns[0]:
        st.caption(
            "RECOMMENDATION"
        )
        st.markdown(
            f"**{esc(recommendation(case))}**"
        )

    with columns[1]:
        st.caption(
            "PRICING LOADING"
        )
        st.markdown(
            f"**{esc(extract_loading(case) or '0%')}**"
        )

    with columns[2]:
        st.caption(
            "CONFIDENCE"
        )
        st.markdown(
            f"**{esc(extract_confidence(case) or '—')}**"
        )

    factors = (
        result.get(
            "risk_factors"
        )
        or risk_assessment(case).get(
            "risk_factors"
        )
        or []
    )

    if factors:

        st.markdown(
            "#### Risk Factors"
        )

        risk_factors(
            factors
        )

    pricing = (
        result.get(
            "pricing"
        )
        or result.get(
            "pricing_result"
        )
        or {}
    )

    if isinstance(
        pricing,
        dict,
    ) and pricing:

        st.markdown(
            "#### Pricing"
        )

        render_key_value_grid(
            pricing
        )


# ============================================================
# AGENT 3 / REFLECTION
# ============================================================

def render_agent3_section(
    case: dict[str, Any],
) -> None:
    section_title(
        "Agent 3 · Reflection & Quality",
        "Constitutional checks and multi-persona reflection for complex or high-risk cases.",
    )

    result = get_agent_result(
        case,
        3,
    )

    constitutional = (
        case.get("constitutional_results")
        or result.get("constitutional_results")
        or result.get("constitutional")
        or {}
    )

    if not constitutional:
        constitutional = {}
        for key in (
            "constitutional_medical_accuracy",
            "constitutional_actuarial_soundness",
            "constitutional_regulatory_compliance",
            "constitutional_fairness",
            "constitutional_explainability",
        ):
            value = case.get(key)
            if value:
                constitutional[key.replace("constitutional_", "")] = value

    reflection = (
        case.get("reflection_personas")
        or case.get("mar_persona_outputs")
        or result.get("reflection_personas")
        or result.get("mar_persona_outputs")
        or result.get("persona_outputs")
        or result.get("personas")
        or []
    )

    if not result and not constitutional and not reflection:
        st.info(
            "Agent 3 has not produced a reflection result for this case."
        )
        return

    mode = (
        case.get(
            "reflection_mode"
        )
        or result.get(
            "reflection_mode"
        )
    )

    round_number = (
        case.get(
            "reflection_round"
        )
        or result.get(
            "reflection_round"
        )
    )

    columns = st.columns(3)

    with columns[0]:
        st.caption("REFLECTION MODE")
        st.write(
            humanize(mode)
            if mode
            else "Not specified"
        )

    with columns[1]:
        st.caption("REFLECTION ROUND")
        st.write(
            text(round_number)
        )

    with columns[2]:
        st.caption("QUALITY VERDICT")
        verdict = (
            case.get("reflection_verdict")
            or result.get("verdict")
            or result.get("final_verdict")
            or "Completed"
        )
        st.write(
            humanize(verdict)
        )

    if constitutional:

        st.divider()

        st.markdown(
            "#### Constitutional Checks"
        )

        if isinstance(
            constitutional,
            dict,
        ):

            for key, value in constitutional.items():

                passed = None
                message = value

                if isinstance(
                    value,
                    dict,
                ):
                    passed = value.get(
                        "passed"
                    )
                    message = (
                        value.get(
                            "message"
                        )
                        or value.get(
                            "reason"
                        )
                        or value.get(
                            "result"
                        )
                        or ""
                    )

                columns = st.columns(
                    [
                        2,
                        1,
                        4,
                    ]
                )

                with columns[0]:
                    st.write(
                        humanize(key)
                    )

                with columns[1]:
                    if passed is True:
                        st.success(
                            "PASS"
                        )
                    elif passed is False:
                        st.error(
                            "FLAG"
                        )
                    else:
                        st.write(
                            "—"
                        )

                with columns[2]:
                    st.write(
                        str(message)
                    )

    findings = case.get("reflection_findings") or result.get("reflection_findings") or []
    if findings:
        st.divider()
        st.markdown("#### Reflection Findings")
        for finding in findings:
            if isinstance(finding, dict):
                st.write(f"• {finding.get('finding') or finding.get('message') or finding.get('reason') or finding}")
            else:
                st.write(f"• {finding}")

    if isinstance(
        reflection,
        dict,
    ):
        reflection = [
            {
                "persona": key,
                "output": value,
            }
            for key, value in reflection.items()
        ]

    if reflection:

        st.divider()

        st.markdown(
            "#### Multi-Agent Reflection"
        )

        for persona in reflection:

            if isinstance(
                persona,
                dict,
            ):

                name = (
                    persona.get(
                        "persona"
                    )
                    or persona.get(
                        "role"
                    )
                    or "Reviewer"
                )

                verdict = (
                    persona.get(
                        "verdict"
                    )
                    or persona.get(
                        "decision"
                    )
                )

                argument = (
                    persona.get(
                        "argument"
                    )
                    or persona.get(
                        "key_argument"
                    )
                    or persona.get(
                        "reasoning"
                    )
                    or persona.get(
                        "output"
                    )
                )

                with st.expander(
                    humanize(name),
                    expanded=True,
                ):

                    if verdict:
                        st.caption(
                            "VERDICT"
                        )
                        st.write(
                            humanize(verdict)
                        )

                    if argument:
                        st.write(
                            argument
                        )

            else:
                st.write(
                    persona
                )


    metrics = (
        result.get("metrics")
        or result.get("agent_metrics")
        or {}
    )
    if metrics:
        st.divider()
        agent_metrics(metrics, "Agent 3 / Reflection")
# ============================================================
# DECISION SECTION
# ============================================================

def render_decision_section(
    case: dict[str, Any],
) -> None:
    section_title(
        "Final Underwriting Result",
        "The consolidated decision package generated by the underwriting workflow.",
    )

    score = overall_risk(
        case
    )

    if score is None:
        st.info(
            "The case has not been underwritten yet."
        )
        return

    # Main result block.
    columns = st.columns(
        [1.3, 2, 1.5, 1.5]
    )

    with columns[0]:
        st.caption(
            "OVERALL RISK"
        )
        st.markdown(
            f"## {risk_display(score)}"
        )
        st.caption(
            risk_band(score)
        )

    with columns[1]:
        st.caption(
            "AUTOMATED RECOMMENDATION"
        )
        st.markdown(
            f"## {esc(recommendation(case))}"
        )

    with columns[2]:
        st.caption(
            "FINAL DECISION"
        )
        st.markdown(
            f"## {esc(decision(case))}"
        )

    with columns[3]:
        st.caption(
            "CONFIDENCE"
        )
        st.markdown(
            f"## {esc(extract_confidence(case) or '—')}"
        )

    st.divider()

    render_decision_details(
        case
    )


def render_decision_details(
    case: dict[str, Any],
) -> None:
    final_decision = case.get(
        "final_decision"
    )

    if not isinstance(
        final_decision,
        dict,
    ):
        final_decision = {}

    risk = risk_assessment(
        case
    )

    factors = (
        final_decision.get(
            "risk_factors"
        )
        or risk.get(
            "risk_factors"
        )
        or get_agent_result(
            case,
            2,
        ).get(
            "risk_factors"
        )
        or []
    )

    coverage_gaps = (
        final_decision.get(
            "coverage_gaps"
        )
        or case.get(
            "coverage_gaps"
        )
        or risk.get(
            "coverage_gaps"
        )
        or []
    )

    state = case.get("state")
    if not isinstance(state, dict):
        state = {}

    agent2 = get_agent_result(
        case,
        2,
    )

    reasoning = (
        final_decision.get("reasoning")
        or final_decision.get("rationale")
        or case.get("reasoning")
        or case.get("rationale")
        or state.get("reasoning")
        or state.get("rationale")
        or risk.get("reasoning")
        or risk.get("rationale")
        or agent2.get("reasoning")
        or agent2.get("rationale")
    )

    if not reasoning:
        risk_score = overall_risk(case)
        rec = recommendation(case)
        loading = extract_loading(case)
        price = (
            final_decision.get("pricing")
            or risk.get("pricing")
            or agent2.get("pricing")
            or {}
        )

        rationale_parts = []
        if factors:
            rationale_parts.append(
                "The decision was based on the identified risk drivers: "
                + "; ".join(
                    str(
                        factor.get("factor")
                        or factor.get("description")
                        or factor.get("reason")
                    )
                    if isinstance(factor, dict)
                    else str(factor)
                    for factor in factors[:4]
                )
                + "."
            )
        if risk_score is not None:
            rationale_parts.append(
                f"The overall risk score is {risk_score:.0f}, "
                f"which maps to a {risk_band(risk_score).lower()} risk band."
            )
        if coverage_gaps:
            rationale_parts.append(
                "Coverage considerations were identified and included in the assessment."
            )
        else:
            rationale_parts.append(
                "No coverage gap was identified by the underwriting assessment."
            )
        if loading not in (None, "", "0", "0%", 0):
            rationale_parts.append(
                f"The recommendation is {rec} with a pricing loading of {loading}."
            )
        elif rec and rec != "Pending":
            rationale_parts.append(
                f"The resulting recommendation is {rec}."
            )

        reasoning = " ".join(rationale_parts)

    columns = st.columns(2)

    with columns[0]:

        st.markdown(
            "#### Risk Drivers"
        )

        if factors:
            for factor in factors:

                if isinstance(
                    factor,
                    dict,
                ):
                    value = (
                        factor.get(
                            "factor"
                        )
                        or factor.get(
                            "description"
                        )
                        or factor.get(
                            "reason"
                        )
                    )
                else:
                    value = factor

                st.write(
                    f"• {value}"
                )
        else:
            st.caption(
                "No structured risk drivers returned."
            )

    with columns[1]:

        st.markdown(
            "#### Coverage Considerations"
        )

        if coverage_gaps:

            for gap in coverage_gaps:

                if isinstance(
                    gap,
                    dict,
                ):

                    description = (
                        gap.get(
                            "gap"
                        )
                        or gap.get(
                            "description"
                        )
                        or "Coverage gap"
                    )

                    severity = gap.get(
                        "severity"
                    )

                    if severity:
                        st.write(
                            f"• {description} "
                            f"— {humanize(severity)}"
                        )
                    else:
                        st.write(
                            f"• {description}"
                        )

                else:
                    st.write(
                        f"• {gap}"
                    )

        else:
            st.caption(
                "No coverage gaps identified."
            )

    if reasoning:

        st.divider()

        st.markdown(
            "#### Underwriting Rationale"
        )

        st.write(
            reasoning
        )

    st.divider()

    st.markdown(
        "#### Pricing"
    )

    pricing = (
        final_decision.get(
            "pricing"
        )
        or final_decision.get(
            "pricing_details"
        )
        or risk.get(
            "pricing"
        )
        or {}
    )

    if isinstance(
        pricing,
        dict,
    ) and pricing:

        render_key_value_grid(
            pricing
        )

    else:

        columns = st.columns(
            3
        )

        with columns[0]:
            st.caption(
                "BASE PREMIUM"
            )
            st.write(
                extract_price(
                    case,
                    "base_premium",
                )
            )

        with columns[1]:
            st.caption(
                "LOADING"
            )
            st.write(
                extract_loading(case)
                or "0%"
            )

        with columns[2]:
            st.caption(
                "FINAL PREMIUM"
            )
            st.write(
                extract_price(
                    case,
                    "final_premium",
                )
            )


def extract_price(
    case: dict[str, Any],
    field: str,
) -> str:
    pricing = case.get("pricing_result")
    if not isinstance(pricing, dict):
        pricing = {}

    candidates = [
        case.get(field),
        pricing.get(field),
        risk_assessment(case).get(field),
        case.get("final_decision"),
    ]

    for value in candidates:

        if isinstance(
            value,
            dict,
        ):
            value = value.get(
                field
            )

        if value is None:
            continue

        return format_currency(
            value
        )

    return "—"


def render_key_value_grid(
    values: dict[str, Any],
) -> None:
    items = [
        (
            key,
            value,
        )
        for key, value in values.items()
        if not isinstance(
            value,
            (
                dict,
                list,
            )
        )
    ]

    if not items:
        return

    for start in range(
        0,
        len(items),
        3,
    ):

        row = items[
            start:start + 3
        ]

        columns = st.columns(
            len(row)
        )

        for column, (
            key,
            value,
        ) in zip(
            columns,
            row,
        ):
            with column:
                st.caption(
                    humanize(key).upper()
                )
                st.write(
                    text(value)
                )


# ============================================================
# WORKFLOW
# ============================================================

def render_workflow_section(
    case: dict[str, Any],
) -> None:
    section_title(
        "Workflow",
        "Execution trace and persisted underwriting events.",
    )
    workflow_metrics(
        case.get("workflow_metrics")
        or case.get("metrics")
        or {}
    )

    agent_usage = case.get("agent_metrics")
    if isinstance(agent_usage, dict) and agent_usage:
        st.divider()
        st.markdown("#### Agent Latency & Token Usage")
        workflow_metrics({"agents": agent_usage})
    trace = case.get(
        "workflow_trace"
    )

    if not isinstance(
        trace,
        list,
    ):
        trace = []

    if trace:

        workflow_timeline(
            trace
        )

    events = load_events(
        str(
            case.get(
                "case_id",
                "",
            )
        )
    )

    if events:

        st.divider()

        st.markdown(
            "#### Persisted Workflow Events"
        )

        for event in events:

            if not isinstance(
                event,
                dict,
            ):
                continue

            node = (
                event.get(
                    "node"
                )
                or event.get(
                    "event_type"
                )
                or "workflow"
            )

            status = event.get(
                "status"
            )

            message = event.get(
                "message"
            )

            columns = st.columns(
                [
                    1.5,
                    1.2,
                    4,
                ]
            )

            with columns[0]:
                st.write(
                    humanize(node)
                )

            with columns[1]:
                st.write(
                    humanize(status)
                )

            with columns[2]:
                st.write(
                    message or ""
                )

    if not trace and not events:
        st.info(
            "No workflow trace is available yet."
        )


# ============================================================
# HUMAN REVIEW
# ============================================================

def render_human_review(
    case: dict[str, Any],
) -> None:
    section_title(
        "Human Review",
        "Evidence-backed reviewer workspace for cases requiring human intervention.",
    )

    status = status_key(
        case.get("status")
        or case.get("processing_status")
    )

    if status not in {
        "human-review",
        "review",
        "awaiting-human-review",
        "escalated",
    }:

        st.info(
            "This case is not currently waiting for human review."
        )

    score = overall_risk(
        case
    )

    if score is not None:

        columns = st.columns(4)

        values = [
            (
                "Overall Risk",
                risk_value(
                    case,
                    "overall_risk_score",
                ),
            ),
            (
                "Medical Risk",
                risk_value(
                    case,
                    "medical_risk_score",
                ),
            ),
            (
                "Claims Risk",
                risk_value(
                    case,
                    "claims_risk_score",
                ),
            ),
            (
                "Coverage Gap",
                risk_value(
                    case,
                    "coverage_gap_score",
                ),
            ),
        ]

        for column, (
            label,
            value,
        ) in zip(
            columns,
            values,
        ):
            with column:
                st.caption(
                    label.upper()
                )
                st.markdown(
                    f"### {text(value)}"
                )

    risk = risk_assessment(
        case
    )

    factors = get_list(
        risk,
        "risk_factors",
    )

    if factors:

        st.divider()

        st.markdown(
            "#### Key Risk Factors"
        )

        risk_factors(
            factors
        )

    evidence = case.get(
        "evidence"
    )

    if isinstance(
        evidence,
        dict,
    ) and evidence:

        st.divider()

        st.markdown(
            "#### Evidence Supporting Review"
        )

        evidence_availability(
            evidence
        )

    reviews = load_reviews(
        str(
            case.get(
                "case_id",
                "",
            )
        )
    )

    if reviews:

        st.divider()

        st.markdown(
            "#### Review History"
        )

        review_summary(
            reviews
        )

    if status not in {
        "human-review",
        "review",
        "awaiting-human-review",
        "escalated",
    }:
        return

    st.divider()

    st.markdown(
        "#### Reviewer Decision"
    )

    action = review_actions(case_id)

    if not action:
        return

    reviewer = action.get(
        "reviewer",
        "Underwriter",
    )

    comments = action.get(
        "comments",
        "",
    )

    case_id = str(
        case.get(
            "case_id"
        )
        or ""
    )

    try:

        if action["action"] == "approve":

            api.approve(
                case_id,
                reviewer=reviewer,
                comments=comments,
            )

        elif action["action"] == "override":

            api.override(
                case_id,
                reviewer=reviewer,
                decision=action.get(
                    "decision",
                    "",
                ),
                comments=comments,
            )

        elif action["action"] == "sendback":

            api.sendback(
                case_id,
                reviewer=reviewer,
                comments=comments,
            )

        elif action["action"] == "escalate":

            api.escalate(
                case_id,
                reviewer=reviewer,
                comments=comments,
            )

        st.session_state.case_cache.pop(
            case_id,
            None,
        )

        st.success(
            "Human review action recorded."
        )

        time.sleep(
            0.4
        )

        st.session_state.workspace_section = (
            "Overview"
        )

        st.rerun()

    except APIError as exc:
        st.error(
            f"Unable to record review decision: {exc}"
        )


# ============================================================
# REVIEW QUEUE
# ============================================================

def render_review_queue() -> None:
    page_header(
        "Human Review",
        "Cases routed to an underwriter for human intervention.",
    )

    cases = load_cases()

    review_cases = [
        case
        for case in cases
        if status_key(
            case.get("status")
            or case.get("processing_status")
        )
        in {
            "human-review",
            "review",
            "awaiting-human-review",
            "escalated",
        }
    ]

    if not review_cases:

        render_empty(
            "No Cases Awaiting Review",
            "The human review queue is currently clear.",
        )

        return

    for case in review_cases:

        case_id = str(
            case.get(
                "case_id",
                "",
            )
        )

        columns = st.columns(
            [
                1.2,
                1.8,
                2.2,
                1.2,
                1.2,
            ]
        )

        with columns[0]:
            st.caption("CASE")
            st.markdown(
                f"**{esc(case_id)}**"
            )

        with columns[1]:
            st.caption("APPLICANT")
            st.markdown(
                f"**{esc(applicant_name(case))}**"
            )

        with columns[2]:
            st.caption("PRODUCT")
            st.write(
                product(case)
            )

        with columns[3]:
            st.caption("RISK")
            st.write(
                risk_display(
                    overall_risk(case)
                )
            )

        with columns[4]:
            if st.button(
                "Review",
                key=f"review_queue_{case_id}",
                use_container_width=True,
            ):
                open_case(
                    case_id,
                    "Human Review",
                )

        st.divider()


# ============================================================
# SYSTEM STATUS
# ============================================================

def render_system_status() -> None:
    page_header(
        "System Status",
        "Connectivity and configuration of the underwriting workstation.",
    )

    try:

        health = normalize_data(
            api.health()
        )

        st.success(
            "Backend API is reachable."
        )

        if isinstance(
            health,
            dict,
        ):

            section_title(
                "Backend Health"
            )

            render_key_value_grid(
                health
            )

    except APIError as exc:

        st.error(
            f"Backend unavailable: {exc}"
        )

    st.divider()

    section_title(
        "Frontend Configuration"
    )

    columns = st.columns(2)

    with columns[0]:
        st.caption(
            "APPLICATION"
        )
        st.write(
            settings.app_name
        )

    with columns[1]:
        st.caption(
            "BACKEND URL"
        )
        st.write(
            settings.backend_url
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    render_sidebar()

    page = st.session_state.page

    if page == "dashboard":
        render_dashboard()

    elif page == "cases":
        render_cases()

    elif page == "review":
        render_review_queue()

    elif page == "applicants":
        render_applicants()

    elif page == "applicant":
        render_applicant_detail()

    elif page == "case":
        render_case_workspace()

    elif page == "system":
        render_system_status()

    else:
        st.session_state.page = "dashboard"
        st.rerun()

    footer(
        "MedUnderwrite AI · Evidence-grounded medical underwriting"
    )


if __name__ == "__main__":
    main()
