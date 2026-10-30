from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

from app.config import settings

logger = logging.getLogger(__name__)

_initialized = False


def _init_env() -> None:
    global _initialized
    if not _initialized:
        if settings.langfuse_public_key:
            os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
        if settings.langfuse_secret_key:
            os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
        if settings.langfuse_host:
            os.environ["LANGFUSE_HOST"] = settings.langfuse_host
        _initialized = True


def is_langfuse_enabled() -> bool:
    """Return True only if Langfuse is enabled AND public & secret keys are configured."""
    has_keys = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
    return bool(settings.langfuse_enabled and has_keys)


def get_langfuse_callback() -> Any | None:
    """Return an initialized Langfuse CallbackHandler for LangChain / LangGraph, or None."""
    if not is_langfuse_enabled():
        return None

    try:
        _init_env()
        from langfuse.langchain import CallbackHandler

        return CallbackHandler(public_key=settings.langfuse_public_key or None)
    except Exception as exc:
        logger.warning("Langfuse callback initialization failed: %s", exc)
        return None


@contextmanager
def trace_context(
    case_id: str,
    applicant_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Generator[None, None, None]:
    """Context manager to propagate trace-level attributes (session_id, user_id, metadata)."""
    if not is_langfuse_enabled():
        yield
        return

    try:
        _init_env()
        from langfuse import propagate_attributes

        merged_metadata = dict(metadata or {})
        merged_metadata["case_id"] = case_id
        merged_metadata["environment"] = settings.environment

        with propagate_attributes(
            session_id=case_id,
            user_id=applicant_id or "unknown",
            metadata=merged_metadata,
            tags=tags or [settings.environment, "underwriting"],
        ):
            yield
    except Exception as exc:
        logger.debug("Failed to propagate Langfuse attributes: %s", exc)
        yield


def record_score(
    case_id: str,
    name: str,
    value: float | str,
    comment: str | None = None,
) -> None:
    """Attach a score or evaluation metric to a case in Langfuse (e.g. human review)."""
    if not is_langfuse_enabled():
        return

    try:
        _init_env()
        from langfuse import get_client

        client = get_client()
        client.create_score(
            session_id=case_id,
            name=name,
            value=value,
            comment=comment,
        )
    except Exception as exc:
        logger.warning("Failed to record Langfuse score for case %s: %s", case_id, exc)


def flush_traces() -> None:
    """Flush pending Langfuse events to ensure traces are delivered."""
    if not is_langfuse_enabled():
        return

    try:
        from langfuse import get_client

        get_client().flush()
    except Exception as exc:
        logger.debug("Langfuse flush warning: %s", exc)
