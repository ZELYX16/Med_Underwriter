from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
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

    yield

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