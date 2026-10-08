from __future__ import annotations

import os
from functools import wraps
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY", "")
LANGCHAIN_PROJECT = os.getenv(
    "LANGCHAIN_PROJECT",
    "medunderwrite-ai",
)
LANGCHAIN_TRACING_V2 = os.getenv(
    "LANGCHAIN_TRACING_V2",
    "true",
)


def configure_langsmith() -> bool:
    """Configure LangSmith tracing from environment variables."""

    if not LANGCHAIN_API_KEY:
        print("[WARN] LANGCHAIN_API_KEY is not configured.")
        print("[INFO] LangSmith tracing is disabled.")
        return False

    os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = LANGCHAIN_PROJECT
    os.environ["LANGCHAIN_TRACING_V2"] = LANGCHAIN_TRACING_V2

    print(
        f"[OK] LangSmith tracing enabled: "
        f"{LANGCHAIN_PROJECT}"
    )

    return True


def trace_agent(
    name: str,
    *,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
):
    """
    Decorator for tracing individual agent functions.

    LangSmith tracing is optional. If LangSmith is unavailable,
    the original function is returned unchanged.
    """

    def decorator(func: Callable[..., Any]):
        try:
            from langsmith import traceable

            traced_function = traceable(
                func,
                name=name,
                run_type="chain",
                tags=tags or [],
                metadata=metadata or {},
            )

        except Exception as exc:
            print(
                f"[WARN] LangSmith tracing unavailable "
                f"for {name}: {exc}"
            )
            traced_function = func

        @wraps(func)
        def wrapper(*args, **kwargs):
            return traced_function(
                *args,
                **kwargs,
            )

        return wrapper

    return decorator


def get_langsmith_status() -> dict[str, Any]:
    """Return current LangSmith configuration status."""

    return {
        "enabled": bool(LANGCHAIN_API_KEY),
        "project": LANGCHAIN_PROJECT,
        "tracing_v2": (
            LANGCHAIN_TRACING_V2.lower() == "true"
        ),
        "api_key_configured": bool(LANGCHAIN_API_KEY),
    }


def add_case_metadata(
    case_id: str,
    agent: str,
    **metadata: Any,
) -> dict[str, Any]:
    """Build consistent metadata for case-level traces."""

    return {
        "case_id": case_id,
        "agent": agent,
        **metadata,
    }


configure_langsmith()