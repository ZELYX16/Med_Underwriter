from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.store.state_store import state_store


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    settings.data_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    settings.sqlite_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    settings.chroma_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Initialize the SQLite state store.
    state_store.initialize()

    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "AI-assisted medical insurance underwriting "
        "decision-support system."
    ),
    debug=settings.debug,
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


app.include_router(router)


@app.get(
    "/",
    tags=["System"],
)
async def root():
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }


@app.get(
    "/health",
    tags=["System"],
)
async def health():
    return {
        "status": "healthy",
        "service": settings.app_name,
    }