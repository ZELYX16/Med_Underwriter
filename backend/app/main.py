from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.store.state_store import state_store
from app.store.vector_store import vector_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


async def _warm_models() -> None:
    """Preload Ollama models so the first case doesn't pay the load time."""
    from app.llm.factory import get_llm

    for role in dict.fromkeys(("reasoning", "reflection")):
        try:
            llm = get_llm(role, max_tokens=1)
            await asyncio.to_thread(llm.invoke, "ok")
            logger.info("Warmed %s model (%s)", role, settings.get_model(role))
        except Exception as exc:
            logger.warning("Model warm-up for %s skipped: %s", role, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s v%s",
        settings.app_name,
        settings.app_version,
    )

    state_store.health_check()

    try:
        vector_health = vector_store.health_check()
        logger.info(
            "Vector store: %s",
            vector_health,
        )
    except Exception as exc:
        logger.warning(
            "Vector store health check failed: %s",
            exc,
        )

    warm_task = None
    if settings.llm_provider == "ollama" and settings.warm_llm_on_startup:
        warm_task = asyncio.create_task(_warm_models())

    yield

    if warm_task and not warm_task.done():
        warm_task.cancel()

    logger.info(
        "Shutting down %s",
        settings.app_name,
    )


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "LangGraph-based multi-agent medical insurance "
        "underwriting decision-support system."
    ),
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    router,
    prefix="/api",
)


def _error_body(code: str, message: str, retryable: bool) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    logger.info("Validation error on %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "invalid_request",
            "Some of the submitted information is missing or invalid. "
            "Please check the form and try again.",
            False,
        ),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    # Technical detail is logged; clients only get a stable, safe message.
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content=_error_body(
            "internal_error",
            "The service hit a temporary problem. Please try again in a moment.",
            True,
        ),
    )


@app.get(
    "/",
)
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.get(
    "/health",
)
async def health():
    state_health = state_store.health_check()

    try:
        vector_health = vector_store.health_check()
    except Exception as exc:
        vector_health = {
            "status": "unhealthy",
            "error": str(exc),
        }

    overall_status = (
        "healthy"
        if (
            state_health.get("status") == "healthy"
            and vector_health.get("status") == "healthy"
        )
        else "degraded"
    )

    return {
        "status": overall_status,
        "environment": settings.environment,
        "services": {
            "state_store": state_health,
            "vector_store": vector_health,
            "llm_provider": settings.llm_provider,
        },
    }


@app.get(
    "/api/health",
)
async def api_health():
    return await health()