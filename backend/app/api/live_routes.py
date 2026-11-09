"""
Live intake API: sessions, uploads with triage, sample applicants, submit.

A session owns a draft applicant and case from the start. Uploaded documents
are stored and registered in SQLite while the applicant fills in the form;
extraction and evidence retrieval are deferred until underwriting starts.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.routes import AwaitingDocuments, _prepare_case_for_run, _run_case
from app.config import settings
from app.services import cost_guard, intake, outcome, scenarios
from app.services.document_service import document_service
from app.services.sessions import get_store
from app.services.triage import triage
from app.store.state_store import state_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/live", tags=["live intake"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ok(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "error": None}


def _session(token: str) -> dict[str, Any]:
    session = get_store().get(token)
    if session is None:
        raise HTTPException(status_code=404, detail="This application link has expired or does not exist.")
    return session


def _customer(session: dict[str, Any]) -> dict[str, Any]:
    """What the applicant sees. Never includes scores, flags or internal reasons."""
    items = intake.open_items(session["form"], session["documents"])
    missing_docs = [i["text"].split(".")[0] for i in items if i["kind"] == "document"]
    case = state_store.get_case(session["case_id"]) if session["status"] == "submitted" else None
    if not case:
        done = sum(1 for i in items if i["blocking"]) == 0
        return {"stage": "Your details", "headline": "Complete your application" if not done else "Ready to submit",
                "reason": "We will show your progress here.", "next_steps": [i["text"] for i in items if i["blocking"]][:6]}
    status = str(case.get("final_status") or case.get("status") or "").lower()
    if status == "processing":
        return {"stage": "Assessing", "headline": "We are assessing your application",
                "reason": "This usually takes a few minutes.", "next_steps": []}
    if status == "awaiting_documents":
        names = [m.get("document", "") for m in case.get("missing_documents", []) if m.get("blocking")]
        return {"stage": "Waiting for you", "headline": "We need a document to continue",
                "reason": "Please add the item below and press Submit again.", "next_steps": [f"Please send: {n}" for n in names]}
    level = "straight_through" if status == "completed" else (case.get("decision_level") or "full_review")
    pricing = case.get("pricing_result") or {}
    message = outcome.customer_message(level, str(case.get("agent2_recommendation", "")),
                                       float(pricing.get("loading_percentage", 0) or 0), missing_docs)
    return {"stage": "Decision" if level == "straight_through" else "In review", **message}


def _view(session: dict[str, Any]) -> dict[str, Any]:
    form = session["form"]
    from app.services.clarification_engine import build_clarifications
    clarifications = build_clarifications(form, session["documents"])
    items = intake.open_items(form, session["documents"], clarifications)
    return {
        "token": session["token"], "status": session["status"], "case_id": session["case_id"],
        "form": form, "documents": session["documents"], "meta": session["meta"],
        "required_documents": intake.required_documents(form),
        "open_items": items, "clarifications": clarifications,
        "can_submit": not [i for i in items if i["blocking"]],
        "customer": _customer(session),
    }


def _doc_type(folder: str) -> str:
    return folder if folder in document_service.DOCUMENT_TYPES else "other"


async def _index(token: str, doc_id: str, filename: str, data: bytes, folder: str, session: dict[str, Any]) -> None:
    """Persist the applicant file and SQL metadata; defer extraction until underwriting."""
    try:
        upload = UploadFile(filename=filename, file=io.BytesIO(data))
        result = await document_service.upload_document(
            upload=upload,
            applicant_id=session["applicant_id"],
            case_id=session["case_id"],
            document_type=_doc_type(folder),
        )
        patch = {
            "status": "accepted",
            "document_id": result.get("document_id"),
            "chunks": 0,
            "processing": "deferred_until_underwriting",
        }
    except Exception as exc:
        logger.warning("Storing %s failed: %s", filename, exc)
        patch = {
            "status": "failed",
            "error": "We could not save this file. Please try again.",
        }

    def apply(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in docs:
            if item["id"] == doc_id:
                item.update(patch)
        return docs

    get_store().mutate_documents(token, apply)


async def _ingest(token: str, filename: str, data: bytes, requirement: str | None,
                  background: BackgroundTasks | None, session: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
        tmp.write(data)
    tmp_path = Path(tmp.name)
    try:
        result = await asyncio.to_thread(triage, tmp_path, filename, requirement, session["form"])
    finally:
        tmp_path.unlink(missing_ok=True)

    if any(d["sha256"] == result["sha256"] and d["status"] != "rejected" for d in session["documents"]):
        return {"id": None, "filename": filename, "status": "duplicate",
                "issues": ["You already added this file."], "detected_type": result["detected_type"]}

    entry = {
        "id": uuid.uuid4().hex[:10], "filename": filename, "requirement": requirement,
        "status": result["status"] if result["status"] == "rejected" else "indexing",
        "triage": result["status"], "detected_type": result["detected_type"], "folder": result["folder"],
        "scanned": result["scanned"], "issues": result["issues"], "sha256": result["sha256"],
        "triage_sec": result["timing_sec"], "added_at": time.time(),
    }
    get_store().mutate_documents(token, lambda docs: docs + [entry])
    if entry["status"] == "indexing":
        if background is not None:
            background.add_task(_index, token, entry["id"], filename, data, result["folder"], session)
        else:
            await _index(token, entry["id"], filename, data, result["folder"], session)
    entry["total_sec"] = round(time.perf_counter() - started, 3)
    return entry


async def _warm(token: str, form: dict[str, Any]) -> None:
    """Fetch regulatory and guidance references early, while the applicant is still typing."""
    session = get_store().get(token)
    if not session or session["meta"].get("warmed"):
        return
    started = time.perf_counter()
    try:
        from app.agents.agent1_submission import submission_agent
        from app.cache.pattern_cache import cache_scope

        profile, submission = intake.to_profile_submission(session["applicant_id"], form)
        queries = submission_agent._build_queries(profile, submission)
        declared = profile["medical_conditions"]

        def work() -> None:
            with cache_scope(session["case_id"]):
                submission_agent._retrieve_regulatory(queries["regulatory"], declared)
                submission_agent._retrieve_actuarial_guidance(queries["actuarial"], submission.get("product"), declared)

        await asyncio.to_thread(work)
        meta = {**session["meta"], "warmed": True, "warm_sec": round(time.perf_counter() - started, 3)}
        get_store().update(token, meta=meta)
    except Exception as exc:  # warming is an optimisation, never required
        logger.info("Early retrieval skipped: %s", exc)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@router.get("/catalog")
async def catalog():
    return _ok({
        "conditions": [{"key": c["key"], "label": c["label"], "followups": c["followups"]} for c in intake.CONDITIONS],
        "products": intake.PRODUCTS,
        "scenarios": scenarios.listing(),
    })


class ConditionText(BaseModel):
    text: str
    use_llm: bool = True


@router.post("/condition-lookup")
async def condition_lookup(body: ConditionText):
    found = intake.lookup_condition(body.text)
    if not found["matched"] and body.use_llm and cost_guard.allow("lookup", "condition"):
        try:
            from app.llm.factory import get_llm

            keys = ",".join(c["key"] for c in intake.CONDITIONS)
            reply = await asyncio.to_thread(
                get_llm("planner", max_tokens=40, json_mode=True).invoke,
                f'Pick the best key for this health condition: {keys}, or other. Reply JSON {{"key":"..."}}. '
                f"Condition: {body.text[:80]}",
            )
            key = json.loads(str(getattr(reply, "content", reply)).strip()).get("key")
            if key in intake.BY_KEY:
                c = intake.BY_KEY[key]
                found = {"key": key, "label": c["label"], "group": c["group"], "matched": True, "by": "model"}
        except Exception:
            pass
    return _ok(found)


@router.post("/sessions")
async def create_session():
    token_hint = uuid.uuid4().hex[:6].upper()
    applicant_id, case_id = f"APP-LV-{token_hint}", f"UW-LV-{token_hint}"
    state_store.create_applicant(applicant_id=applicant_id, applicant_profile={"applicant_id": applicant_id, "source": "live_session"},
                                 source="live_session")
    state_store.create_case(case_id=case_id, applicant_id=applicant_id,
                            state={"case_id": case_id, "applicant_id": applicant_id,
                                   "applicant_profile": {"applicant_id": applicant_id}, "submission": {}},
                            status="intake")
    return _ok(_view(get_store().create(applicant_id, case_id)))


@router.get("/sessions/{token}")
async def get_session(token: str):
    return _ok(_view(_session(token)))


class FormBody(BaseModel):
    form: dict[str, Any]


@router.put("/sessions/{token}")
async def save_form(token: str, body: FormBody, background: BackgroundTasks):
    session = _session(token)
    get_store().update(token, form=body.form)
    if body.form.get("product") and body.form.get("conditions") is not None and not session["meta"].get("warmed"):
        background.add_task(_warm, token, body.form)
    return _ok(_view(_session(token)))


@router.post("/sessions/{token}/documents")
async def add_document(token: str, background: BackgroundTasks, file: UploadFile = File(...),
                       requirement: str | None = Form(default=None)):
    session = _session(token)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="That file is empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"That file is too large (limit {settings.max_upload_mb} MB).")
    entry = await _ingest(token, intake_name(file.filename), data, requirement, background, session)
    return _ok({"document": entry, "session": _view(_session(token))})


def intake_name(name: str | None) -> str:
    import re

    return re.sub(r"[^\w.\- ]", "_", Path(name or "document").name) or "document"


@router.delete("/sessions/{token}/documents/{doc_id}")
async def remove_document(token: str, doc_id: str):
    session = _session(token)
    entry = next((d for d in session["documents"] if d["id"] == doc_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if entry.get("document_id"):
        try:  # deletes its chunks and stored file; facts are read per file at run time
            await asyncio.to_thread(document_service.delete_document, applicant_id=session["applicant_id"],
                                    case_id=session["case_id"], document_id=entry["document_id"])
        except Exception as exc:
            logger.warning("Delete of %s failed: %s", entry["document_id"], exc)
    get_store().mutate_documents(token, lambda docs: [d for d in docs if d["id"] != doc_id])
    return _ok(_view(_session(token)))


@router.post("/sessions/{token}/scenario/{scenario_id}")
async def load_scenario(token: str, scenario_id: str, background: BackgroundTasks):
    session = _session(token)
    scenario = scenarios.get(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Unknown sample applicant.")
    for d in session["documents"]:  # start clean
        if d.get("document_id"):
            await remove_document(token, d["id"])
    get_store().update(token, form=scenario["form"], documents=[], meta={})
    # The sample's own applicant folder is the source of its supporting files.
    # The underwriting submission PDF is parsed for autofill, but is not shown
    # as an applicant-uploaded attachment.
    for document in scenario.get("documents") or []:
        raw_path = Path(str(document.get("file_path") or ""))
        if not raw_path.is_file():
            logger.warning("Sample document is missing: %s", raw_path)
            continue
        try:
            payload = raw_path.read_bytes()
            folder = str(document.get("document_type") or "other")
            await _ingest(
                token,
                str(document.get("filename") or raw_path.name),
                payload,
                folder,
                background,
                _session(token),
            )
        except Exception:
            logger.exception("Could not attach sample document %s", raw_path.name)
    background.add_task(_warm, token, scenario["form"])
    return _ok(_view(_session(token)))


@router.post("/sessions/{token}/submit")
async def submit(token: str, background: BackgroundTasks, proceed: bool = False):
    session = _session(token)
    if session.get("status") in {"submitted", "processing"}:
        raise HTTPException(status_code=409, detail="This application is already being processed. Please wait.")
    case_status_info = state_store.get_case_status(session["case_id"])
    if case_status_info and str(case_status_info.get("status", "")).lower() in {"processing", "agent1", "agent2", "agent3"}:
        raise HTTPException(status_code=409, detail="This application is already being processed. Please wait.")

    blocking = [i for i in intake.open_items(session["form"], session["documents"]) if i["blocking"]]
    if blocking:
        return _ok({"status": "incomplete", "open_items": blocking})
    if any(d["status"] == "indexing" for d in session["documents"]):
        return _ok({"status": "indexing", "message": "Your documents are still being read. Please try again in a moment."})

    applicant_id, case_id = session["applicant_id"], session["case_id"]
    profile, submission = intake.to_profile_submission(applicant_id, session["form"])
    state_store.update_applicant(applicant_id=applicant_id, applicant_profile=profile)
    state = state_store.get_case(case_id) or {}
    state.update(applicant_profile=profile, submission=submission, case_id=case_id, applicant_id=applicant_id,
                 final_status="draft", final_decision="", final_recommendation="")
    state_store.save_case(case_id, state, status="draft")
    cost_guard.reset(case_id)

    # Set processing status atomically before launching background task
    state_store.update_case_status(case_id, "processing")
    get_store().update(token, status="processing")

    try:
        prepared = await asyncio.to_thread(_prepare_case_for_run, case_id, proceed)
    except AwaitingDocuments as waiting:
        get_store().update(token, status="collecting")
        state_store.update_case_status(case_id, "awaiting_documents")
        return _ok({"status": "awaiting_documents", "missing": waiting.missing})
    except Exception:
        get_store().update(token, status="draft")
        state_store.update_case_status(case_id, "draft")
        raise
    background.add_task(_run_case, case_id, prepared)
    get_store().update(token, status="submitted")
    return _ok({"status": "submitted", "case_id": case_id})


@router.get("/sessions/{token}/customer")
async def customer_view(token: str):
    return _ok(_customer(_session(token)))


@router.get("/scenarios")
async def scenario_list():
    return _ok(scenarios.listing())