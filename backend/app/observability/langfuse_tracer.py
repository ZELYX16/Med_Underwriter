from __future__ import annotations

import functools
import logging
import os
from contextlib import contextmanager
from typing import Any, Callable, Generator

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
    enabled = getattr(settings, "langfuse_enabled", False)
    pk = getattr(settings, "langfuse_public_key", "")
    sk = getattr(settings, "langfuse_secret_key", "")
    has_keys = bool(pk and sk)
    return bool(enabled and has_keys)


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


def observe_span(name: str | None = None, as_type: str = "span") -> Callable:
    """
    Decorator to wrap async/sync functions as Langfuse trace spans.
    Falls back gracefully to a no-op if Langfuse is disabled or errors.
    """
    def decorator(fn: Callable) -> Callable:
        if not is_langfuse_enabled():
            return fn

        try:
            _init_env()
            from langfuse import observe
            return observe(name=name, as_type=as_type)(fn)
        except Exception as exc:
            logger.debug("Langfuse observe decorator skipped for %s: %s", name, exc)
            return fn

    return decorator


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

    merged_metadata = dict(metadata or {})
    merged_metadata["case_id"] = case_id
    merged_metadata["environment"] = settings.environment

    ctx = None
    try:
        _init_env()
        from langfuse import propagate_attributes
        ctx = propagate_attributes(
            session_id=case_id,
            user_id=applicant_id or "unknown",
            metadata=merged_metadata,
            tags=tags or [settings.environment, "underwriting"],
        )
    except Exception as exc:
        logger.debug("Failed to propagate Langfuse attributes: %s", exc)

    if ctx is not None:
        with ctx:
            yield
    else:
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
        _init_env()
        from langfuse import get_client

        get_client().flush()
    except Exception as exc:
        logger.debug("Langfuse flush warning: %s", exc)
