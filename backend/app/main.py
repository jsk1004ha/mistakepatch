from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import settings
from .db import ensure_paths, init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_paths()
    init_db()
    yield


def create_app() -> FastAPI:
    ensure_paths()
    init_db()

    app = FastAPI(title="MistakePatch API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    uploads_path = Path(settings.storage_path)
    uploads_path.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")

    return app


app = create_app()
