"""
Live application: a plain-language form with documents, shown to the applicant.

The page keeps one server-side session (autosaved, resumable by code). Uploads
are checked and indexed in the background while the form is being filled in;
nothing is underwritten until Submit. A second tab shows exactly what the
customer sees.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Any

import streamlit as st

from api_client import APIError, api

STATUS_TEXT = {
    "indexing": "Reading...", "indexed": "Ready", "accepted": "Ready", "warning": "Check this",
    "rejected": "Not accepted", "failed": "Could not read", "duplicate": "Already added",
    "needs_review": "Needs review", "deleting": "Removing...", "delete_failed": "Removal failed",
}


def _call(method: str, path: str, **kwargs: Any) -> Any:
    try:
        reply = api._request(method, f"/api/live{path}", **kwargs)
    except APIError as exc:
        st.error(exc.user_message)
        return None
    return reply.get("data") if isinstance(reply, dict) else reply


def _load(token: str) -> dict[str, Any] | None:
    view = _call("GET", f"/sessions/{token}")
    if view:
        st.session_state.live_view = view
        st.session_state.live_token = token
    return view


def _start() -> None:
    view = _call("POST", "/sessions")
    if view:
        st.session_state.live_view = view
        st.session_state.live_token = view["token"]
        st.session_state.live_ver = st.session_state.get("live_ver", 0) + 1


def _save(form: dict[str, Any]) -> None:
    view = st.session_state.live_view
    if form != view["form"]:
        updated = _call(
            "PUT",
            f"/sessions/{view['token']}",
            json={"form": form},
        )
        if updated:
            st.session_state.live_view = updated


def _yesno(label: str, key: str, current: Any) -> str:
    index = {"yes": 0, "no": 1}.get(str(current).lower())
    choice = st.radio(
        label,
        ["Yes", "No"],
        index=index,
        horizontal=True,
        key=key,
    )
    return (choice or "").lower()


def _conditions_block(
    form: dict[str, Any],
    catalog: dict[str, Any],
    ver: int,
) -> list[dict[str, Any]]:
    by_label = {c["label"]: c for c in catalog["conditions"]}
    saved = {
        c.get("label"): c
        for c in form.get("conditions", [])
    }

    st.markdown("**Have you ever been diagnosed with any of these conditions?**")

    chosen = st.multiselect(
        "Select all that apply",
        list(by_label),
        default=[label for label in saved if label in by_label],
        key=f"live_cond_{ver}",
        label_visibility="collapsed",
    )

    typed = [
        dict(c)
        for c in form.get("conditions", [])
        if c.get("custom")
    ]

    with st.expander("Add a condition not listed", expanded=False):
        new = st.text_input(
            "Condition name",
            key=f"live_typed_{ver}",
        )

        if st.button("Add condition", key=f"live_add_{ver}") and new.strip():
            found = _call(
                "POST",
                "/condition-lookup",
                json={"text": new, "use_llm": True},
            ) or {}

            label = found.get("label") or new.strip().title()

            if found.get("matched") and label in by_label:
                st.info(f"Please select {label} from the list above.")

            elif not any(
                c.get("label", "").casefold() == label.casefold()
                for c in typed
            ):
                typed.append({
                    "key": found.get("key"),
                    "label": label,
                    "custom": True,
                    "answers": {},
                })

    out = []

    for label in chosen:
        condition = by_label[label]

        out.append({
            "key": condition["key"],
            "label": label,
            "answers": saved.get(label, {}).get("answers", {}),
        })

    out.extend(typed)

    st.caption(
        "You do not need to repeat diagnosis dates or medication details here. "
        "Upload relevant reports and prescriptions; we will extract what they "
        "contain and ask only about important missing information."
    )

    return out


def _upload_for_requirement(view: dict[str, Any], requirement_id: str, label: str, ver: int) -> None:
    """Render a dedicated upload control and preserve its requirement ID."""
    uploads = st.file_uploader(
        label,
        type=["pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "txt", "csv", "json"],
        accept_multiple_files=True,
        key=f"live_req_upload_{ver}_{requirement_id}",
    )
    if not uploads:
        return
    import hashlib
    sent = st.session_state.setdefault("live_sent", set())
    changed = False
    for upload in uploads:
        payload = upload.getvalue()
        signature = hashlib.sha256(payload).hexdigest()
        if signature in sent:
            continue
        reply = _call(
            "POST", f"/sessions/{view['token']}/documents",
            files={"file": (upload.name, payload, upload.type or "application/octet-stream")},
            data={"requirement": requirement_id},
        )
        if reply:
            sent.add(signature)
            changed = True
    if changed:
        st.rerun()


def _documents_block(
    view: dict[str, Any],
    form: dict[str, Any],
    ver: int,
) -> None:
    st.markdown("### Medical and supporting documents")

    st.caption(
        "You can upload several PDFs or images together. Include medical "
        "reports, prescriptions, lab results, previous policies and claim records."
    )

    docs = view.get("documents", [])
    needs = view.get("required_documents", [])
    later = set(form.get("docs_later", []))

    template_meta = view.get("meta") or {}
    template_status = template_meta.get("template_documents_status")
    if template_status == "bundle_missing":
        st.error(template_meta.get("template_documents_message", "Sample document bundle is missing."))
    elif template_status == "invalid_bundle":
        st.error(template_meta.get("template_documents_message", "Sample document bundle is invalid."))
    elif template_status == "no_matching_documents":
        st.warning(template_meta.get("template_documents_message", "No supported PDFs were found in the sample bundle."))
    elif template_status == "attached":
        st.success(template_meta.get("template_documents_message", "Sample documents were queued for processing."))

    uploads = st.file_uploader(
        "Upload supporting documents",
        type=[
            "pdf", "png", "jpg", "jpeg", "tif",
            "tiff", "bmp", "txt", "csv", "json",
        ],
        accept_multiple_files=True,
        key=f"live_all_uploads_{ver}",
        help="Select multiple files at once. The document pipeline will inspect and classify them.",
    )

    if uploads:
        import hashlib

        sent = st.session_state.setdefault("live_sent", set())
        uploaded_any = False

        for upload in uploads:
            payload = upload.getvalue()
            signature = hashlib.sha256(payload).hexdigest()

            if signature in sent:
                continue

            reply = _call(
                "POST",
                f"/sessions/{view['token']}/documents",
                files={
                    "file": (
                        upload.name,
                        payload,
                        upload.type or "application/octet-stream",
                    )
                },
                data={"requirement": ""},
            )

            if reply:
                sent.add(signature)
                uploaded_any = True

        if uploaded_any:
            st.rerun()

    if needs:
        with st.expander(
            "Documents requested for your application",
            expanded=True,
        ):
            for need in needs:
                have = [
                    d for d in docs
                    if d.get("status") != "rejected"
                    and (
                        d.get("requirement") == need["id"]
                        or (
                            need["id"] == "medical_exam"
                            and d.get("detected_type") == "medical_exam"
                        )
                        or (
                            need["id"] == "policy"
                            and (
                                d.get("folder") == "policy"
                                or d.get("detected_type") == "policy"
                            )
                        )
                        or (
                            need["id"] == "claims"
                            and (
                                d.get("folder") == "claims"
                                or d.get("detected_type") == "claim"
                            )
                        )
                        or (
                            need["id"].startswith("bp_")
                            and d.get("detected_type") in {"medical_exam", "lab", "specialist", "prescription", "discharge"}
                        )
                        or (
                            need["id"].startswith("diabetes_")
                            and d.get("detected_type") in {"lab", "medical_exam", "specialist"}
                        )
                    )
                ]

                label = "Required" if need["blocking"] else "Helpful"

                st.markdown(f"**{label}: {need['document']}**")
                st.caption(need["why"])
                _upload_for_requirement(
                    view, need["id"], f"Upload {need['document']}", ver
                )

                if have:
                    st.success(
                        "Added: " + ", ".join(d["filename"] for d in have)
                    )

                elif need["id"] in later:
                    st.caption("You said you will add this later.")

                else:
                    st.caption(
                        "If you have this document, include it in the upload area above."
                    )

                if not need["blocking"]:
                    will_add_later = st.checkbox(
                        "I will add this later",
                        value=need["id"] in later,
                        key=f"live_later_{ver}_{need['id']}",
                    )

                    if will_add_later:
                        later.add(need["id"])
                    else:
                        later.discard(need["id"])

    form["docs_later"] = sorted(later)

    if docs:
        st.markdown("**Uploaded files**")

        for d in docs:
            cols = st.columns([3, 1.4, 2.6, 1])

            cols[0].write(d.get("filename", "Document"))

            cols[1].write(
                STATUS_TEXT.get(
                    d.get("status"),
                    d.get("status", "Unknown"),
                )
            )

            timing = f"checked {d.get('triage_sec', 0):.2f}s"

            if d.get("index_sec"):
                timing += f", read {d['index_sec']:.1f}s"

            cols[2].caption(timing)

            if cols[3].button(
                "Remove",
                key=f"live_rm_{d['id']}",
            ):
                updated = _call(
                    "DELETE",
                    f"/sessions/{view['token']}/documents/{d['id']}",
                )

                if updated:
                    st.session_state.live_view = updated
                    st.rerun()

            for issue in d.get("issues", []):
                st.warning(issue)

            evidence_types = d.get("evidence_types") or []

            if evidence_types or d.get("fact_count"):
                with st.expander(
                    f"What we found in {d.get('filename', 'this document')}",
                    expanded=False,
                ):
                    if evidence_types:
                        st.caption(
                            "Evidence categories: "
                            + ", ".join(
                                str(x).replace("_", " ")
                                for x in evidence_types
                            )
                        )

                    st.caption(
                        d.get("extraction_summary")
                        or "Evidence extracted from this document."
                    )

                    facts = d.get("extracted_facts") or []

                    for fact in facts[:8]:
                        page = (
                            f" · page {fact['page']}"
                            if fact.get("page")
                            else ""
                        )

                        st.write(
                            f"**{str(fact.get('fact_type', 'Fact')).replace('_', ' ').title()}**: "
                            f"{fact.get('value', '')}{page}"
                        )

                    if int(d.get("fact_count") or 0) > len(facts):
                        st.caption(
                            f"Showing {len(facts)} of {d.get('fact_count')} extracted facts."
                        )

                    for conflict in d.get("conflicts", []):
                        st.warning(
                            f"Please verify {conflict.get('fact_type', 'this result')} dated "
                            f"{conflict.get('date')}: this document says "
                            f"{conflict.get('current_value')} while "
                            f"{conflict.get('previous_document')} says "
                            f"{conflict.get('previous_value')}."
                        )

            if d.get("status") == "needs_review" and d.get("error"):
                st.warning(d["error"])

        if any(d.get("status") == "indexing" for d in docs):
            st.info(
                "We are reading your documents. You can continue completing the application."
            )

            tries = st.session_state.get("live_poll", 0)

            if tries < 40:
                st.session_state.live_poll = tries + 1
                time.sleep(1.5)
                _load(view["token"])
                st.rerun()

        else:
            st.session_state.live_poll = 0


def _clarifications_block(
    view: dict[str, Any],
    form: dict[str, Any],
    ver: int,
) -> None:
    """Render only evidence-driven questions still open for this applicant."""
    questions = view.get("clarifications") or []

    if not questions:
        st.markdown("### Additional information")
        st.success(
            "No additional clarification is currently needed based on the information provided."
        )
        return

    st.markdown("### A few details to confirm")

    st.caption(
        "These questions are generated from your declarations and uploaded records. "
        "If you are unsure, choose the reviewer option rather than guessing."
    )

    answers = dict(form.get("clarification_answers") or {})
    seen_qids = set()

    for index, item in enumerate(questions):
        qid = item["id"]
        if qid in seen_qids:
            continue
        seen_qids.add(qid)
        saved = answers.get(qid, item.get("answer", ""))

        with st.container(border=True):
            st.markdown(
                f"**{item.get('question', item.get('text', 'Please provide more information.'))}**"
            )

            st.caption(
                item.get(
                    "reason",
                    "This information may help complete the assessment.",
                )
            )

            if item.get("evidence"):
                with st.expander("Evidence considered", expanded=False):
                    for source in item["evidence"]:
                        page = (
                            f" · page {source.get('page')}"
                            if source.get("page")
                            else ""
                        )

                        st.write(
                            f"{source.get('filename', 'Document')}{page}: "
                            f"{source.get('value', '')}"
                        )

                        if source.get("excerpt"):
                            st.caption(source["excerpt"])

            input_type = item.get("input_type", "text")
            key = f"live_clarification_{ver}_{qid}"

            if input_type in {"choice", "confirmation", "yes_no_unsure"}:
                options = item.get("options") or (
                    ["Yes", "No", "Not sure"]
                    if input_type == "yes_no_unsure"
                    else []
                )

                if input_type == "yes_no_unsure":
                    options = [
                        "Yes",
                        "No",
                        "Not sure — reviewer should verify",
                    ]

                options = ["— Select an answer —"] + options

                if saved and saved not in options:
                    options.insert(1, saved)

                value = st.selectbox(
                    "Your answer",
                    options,
                    index=options.index(saved) if saved in options else 0,
                    key=key,
                )

            else:
                value = st.text_area(
                    "Your answer",
                    value=str(saved or ""),
                    key=key,
                    height=75,
                    placeholder="Enter the details, or leave blank if you do not know.",
                )

            answers[qid] = value

            if item.get("upload_category"):
                st.caption("If this information is in a document, you can upload it here instead of typing it again.")
                _upload_for_requirement(
                    view, qid, item.get("upload_label") or "Upload supporting document", ver
                )

            if item.get("needs_human_review"):
                st.warning(
                    "This item is marked for underwriter verification. "
                    "You can update your answer if you learn more."
                )

    form["clarification_answers"] = answers

    # Keep the familiar form fields populated as well, so existing profile
    # construction and downstream agents receive the applicant's response.
    field_map = {
        "history:hospital_details": "hospital_details",
        "history:claims_details": "claims_details",
        "history:previous_policy": "previous_insurance_details",
    }

    for qid, field in field_map.items():
        if answers.get(qid):
            form[field] = answers[qid]


def _application_tab(
    view: dict[str, Any],
    catalog: dict[str, Any],
) -> None:
    ver = st.session_state.get("live_ver", 0)
    form = dict(view["form"])

    st.markdown("### Applicant details")

    c1, c2, c3 = st.columns(3)

    form["name"] = c1.text_input(
        "Full name",
        value=form.get("name", ""),
        key=f"live_name_{ver}",
    )

    dob_value = form.get("dob")

    try:
        dob_default = (
            date.fromisoformat(dob_value)
            if dob_value
            else date(1990, 1, 1)
        )
    except ValueError:
        dob_default = date(1990, 1, 1)

    dob = c2.date_input(
        "Date of birth",
        value=dob_default,
        min_value=date(1920, 1, 1),
        max_value=date.today(),
        key=f"live_dob_{ver}",
    )

    form["dob"] = dob.isoformat()

    sexes = ["Female", "Male", "Other"]

    form["sex"] = c3.selectbox(
        "Sex",
        sexes,
        index=sexes.index(form["sex"])
        if form.get("sex") in sexes
        else 0,
        key=f"live_sex_{ver}",
    )

    c4, c5, c6 = st.columns(3)

    form["email"] = c4.text_input(
        "Email address",
        value=form.get("email", ""),
        key=f"live_email_{ver}",
    )

    form["phone"] = c5.text_input(
        "Mobile number",
        value=form.get("phone", ""),
        key=f"live_phone_{ver}",
    )

    form["occupation"] = c6.text_input(
        "Occupation",
        value=form.get("occupation", ""),
        key=f"live_occupation_{ver}",
    )

    form["address"] = st.text_area(
        "Residential address",
        value=form.get("address", ""),
        key=f"live_address_{ver}",
        height=70,
    )

    st.markdown("### Policy details")

    p1, p2, p3 = st.columns(3)

    products = list(catalog["products"])
    if form.get("product") and form["product"] not in products:
        products.append(form["product"])

    form["product"] = p1.selectbox(
        "Plan",
        products,
        index=products.index(form["product"])
        if form.get("product") in products
        else 0,
        key=f"live_prod_{ver}",
    )

    policy_types = ["Individual", "Family Floater"]
    if form.get("policy_type") and form["policy_type"] not in policy_types:
        policy_types.append(form["policy_type"])

    form["policy_type"] = p2.selectbox(
        "Policy type",
        policy_types,
        index=policy_types.index(
            form.get("policy_type", "Individual")
        )
        if form.get("policy_type", "Individual") in policy_types
        else 0,
        key=f"live_policy_type_{ver}",
    )

    form["term_years"] = p3.selectbox(
        "Policy term",
        [1, 2, 3],
        index=[1, 2, 3].index(
            int(form.get("term_years") or 1)
        )
        if int(form.get("term_years") or 1) in [1, 2, 3]
        else 0,
        key=f"live_term_{ver}",
    )

    form["sum_insured"] = st.number_input(
        "Cover amount (INR)",
        100000,
        20000000,
        int(form.get("sum_insured") or 500000),
        step=100000,
        key=f"live_sum_{ver}",
    )

    if "top-up" in str(form.get("policy_type", "")).lower() or form.get("deductible"):
        form["deductible"] = st.number_input(
            "Deductible (INR)",
            min_value=0,
            max_value=20000000,
            value=int(form.get("deductible") or 0),
            step=100000,
            key=f"live_deductible_{ver}",
        )

    if form["policy_type"] == "Family Floater":
        st.markdown("**Family members to be covered**")

        count = st.number_input(
            "Number of additional members",
            min_value=1,
            max_value=6,
            value=max(1, len(form.get("family_members", []))),
            step=1,
            key=f"live_family_count_{ver}",
        )

        existing = form.get("family_members", [])
        members = []

        for index in range(int(count)):
            previous = (
                existing[index]
                if index < len(existing)
                else {}
            )

            with st.container(border=True):
                st.caption(f"Member {index + 1}")
                m1, m2, m3 = st.columns(3)

                member = {
                    "name": m1.text_input(
                        "Full name",
                        value=previous.get("name", ""),
                        key=f"live_fam_name_{ver}_{index}",
                    ),
                    "relationship": m2.selectbox(
                        "Relationship",
                        ["Spouse", "Child", "Parent", "Other"],
                        index=[
                            "Spouse", "Child", "Parent", "Other"
                        ].index(
                            previous.get("relationship", "Spouse")
                        )
                        if previous.get("relationship", "Spouse")
                        in ["Spouse", "Child", "Parent", "Other"]
                        else 0,
                        key=f"live_fam_rel_{ver}_{index}",
                    ),
                    "date_of_birth": m3.text_input(
                        "Date of birth (YYYY-MM-DD)",
                        value=previous.get("date_of_birth", ""),
                        key=f"live_fam_dob_{ver}_{index}",
                    ),
                }

                members.append(member)

        form["family_members"] = members

    else:
        form["family_members"] = []

    st.markdown("### Health and lifestyle declaration")

    form["conditions"] = _conditions_block(
        form,
        catalog,
        ver,
    )

    c1, c2, c3 = st.columns(3)

    with c1:
        form["smoker"] = _yesno(
            "Do you smoke or use tobacco?",
            f"live_smk_{ver}",
            form.get("smoker"),
        )

    with c2:
        alcohol_options = [
            "Prefer not to say",
            "Never",
            "Occasionally",
            "Regularly",
        ]

        form["alcohol_consumption"] = st.selectbox(
            "Alcohol consumption",
            alcohol_options,
            index=alcohol_options.index(
                form.get("alcohol_consumption", "Prefer not to say")
            )
            if form.get("alcohol_consumption", "Prefer not to say")
            in alcohol_options
            else 0,
            key=f"live_alcohol_{ver}",
        )

    with c3:
        form["hospital_stay"] = _yesno(
            "Hospital stay in the last 5 years?",
            f"live_hosp_{ver}",
            form.get("hospital_stay"),
        )

    c4, c5 = st.columns(2)

    with c4:
        form["had_claims"] = _yesno(
            "Have you made a health-insurance claim before?",
            f"live_clm_{ver}",
            form.get("had_claims"),
        )

    with c5:
        form["has_other_insurance"] = _yesno(
            "Do you have another health policy?",
            f"live_oth_{ver}",
            form.get("has_other_insurance"),
        )

    # Persist declaration changes before deriving document requirements and
    # clarification questions, so the UI never lags one interaction behind.
    _save(form)
    view = st.session_state.live_view
    _documents_block(view, form, ver)
    _clarifications_block(view, form, ver)

    form["remarks"] = st.text_area(
        "Anything else you would like us to know? (optional)",
        value=form.get("remarks", ""),
        key=f"live_rem_{ver}",
        height=70,
    )

    form["consent"] = st.checkbox(
        "I confirm these details are true and I agree that you may use them to assess my application.",
        value=bool(form.get("consent")),
        key=f"live_consent_{ver}",
    )

    _save(form)
    view = st.session_state.live_view

    st.markdown("### Application readiness")

    blocking = [
        item for item in view["open_items"]
        if item["blocking"]
    ]

    if blocking:
        for item in blocking:
            st.markdown(
                f"- **Needed:** "
                f"{item.get('text', item.get('question', 'Please provide the requested information.'))}"
            )
    else:
        st.success("Your application is ready to submit.")

    optional = [
        item for item in view["open_items"]
        if not item["blocking"]
    ]

    if optional:
        with st.expander(
            "Items for underwriter verification or later submission"
        ):
            for item in optional:
                st.write(
                    f"- {item.get('text', item.get('question', 'Additional review required.'))}"
                )

    if st.button(
        "Submit application",
        type="primary",
        disabled=bool(blocking),
        use_container_width=True,
    ):
        _submit(view["token"], proceed=False)

    if st.session_state.get("live_awaiting"):
        st.warning(
            "A required document is missing: "
            + ", ".join(
                m.get("document", "")
                for m in st.session_state.live_awaiting
            )
        )

        if st.button("Submit without these documents"):
            _submit(view["token"], proceed=True)


def _submit(token: str, proceed: bool) -> None:
    reply = _call(
        "POST",
        f"/sessions/{token}/submit",
        params={"proceed": "true"} if proceed else None,
    )

    if not reply:
        return

    status = reply.get("status")

    st.session_state.live_awaiting = (
        reply.get("missing")
        if status == "awaiting_documents"
        else None
    )

    if status == "submitted":
        st.session_state.live_case_id = reply["case_id"]
        _load(token)
        st.success(
            "Application submitted. See the customer tab for progress."
        )

    elif status == "indexing":
        st.info(reply["message"])

    elif status == "incomplete":
        st.error("Some details are still missing.")


def _customer_tab(view: dict[str, Any]) -> None:
    st.caption(
        "This is exactly what the applicant sees. "
        "No scores or internal reasons are shown here."
    )

    if st.button("Refresh status"):
        _load(view["token"])
        view = st.session_state.live_view

    cust = view["customer"]

    with st.container(border=True):
        st.caption(cust.get("stage", "").upper())
        st.markdown(f"## {cust['headline']}")
        st.write(cust["reason"])

        for step in cust.get("next_steps", []):
            st.markdown(f"- {step}")

    st.caption(f"Your resume code: `{view['token']}`")



def render_live_intake() -> None:
    st.markdown("## Medical insurance application")

    st.caption(
        "A guided, document-first application. Your progress is saved "
        "automatically, and you can return using your resume code."
    )

    top = st.columns([2, 2, 1.5])

    with top[0]:
        code = st.text_input(
            "Resume with a code",
            key="live_resume",
            placeholder="Paste your code",
        )

        if (
            code
            and code != st.session_state.get("live_token")
            and st.button("Resume")
        ):
            _load(code.strip())
            st.session_state.live_ver = (
                st.session_state.get("live_ver", 0) + 1
            )
            st.rerun()

    catalog = (
        st.session_state.get("live_catalog")
        or _call("GET", "/catalog")
    )

    if not catalog:
        return

    st.session_state.live_catalog = catalog

    with top[1]:
        scenario_by_label = {
            s["label"]: s
            for s in catalog["scenarios"]
        }

        pick = st.selectbox(
            "Load a sample applicant",
            ["(none)"] + list(scenario_by_label),
            key="live_pick",
        )

        selected_scenario = scenario_by_label.get(pick)

        if (
            selected_scenario
            and selected_scenario.get("documents_expected")
            and not selected_scenario.get("has_documents")
        ):
            st.warning(
                "This sample references a document bundle that is not "
                "included in the current project files. Its applicant "
                "and medical details can still be loaded, but sample "
                "documents will not appear."
            )

        if (
            pick != "(none)"
            and st.button("Fill the form with this applicant")
        ):
            if not st.session_state.get("live_token"):
                _start()

            with st.spinner(
                "Filling the form and reading any documents..."
            ):
                view = _call(
                    "POST",
                    f"/sessions/{st.session_state.live_token}/scenario/"
                    f"{scenario_by_label[pick]['id']}",
                )

            if view:
                st.session_state.live_view = view
                st.session_state.live_ver = (
                    st.session_state.get("live_ver", 0) + 1
                )
                st.session_state.live_sent = set()
                st.rerun()

    with top[2]:
        st.write("")

        if st.button("Start a new application"):
            st.session_state.pop("live_token", None)
            st.session_state.pop("live_view", None)
            st.session_state.live_awaiting = None
            _start()
            st.rerun()

    if not st.session_state.get("live_token"):
        _start()

    view = st.session_state.get("live_view")

    if not view:
        return

    tab_apply, tab_customer = st.tabs(
        ["Application", "What the customer sees"]
    )

    with tab_apply:
        if view.get("status") == "submitted":
            st.success("Your application has been submitted. Your answers and documents are saved.")
            st.info("Use the customer status tab to follow progress. If the underwriting team requests more information, you can return with your resume code.")
        else:
            _application_tab(view, catalog)

    with tab_customer:
        _customer_tab(st.session_state.live_view)