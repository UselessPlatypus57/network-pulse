import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__, observability
from app.config import settings
from app.db import get_db, init_db
from app.evaluator import evaluation_loop
from app.routers import alerts, chaos, health, metrics, sites

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    task: asyncio.Task | None = None
    if os.getenv("EVALUATOR_ENABLED", "true").lower() != "false":
        task = asyncio.create_task(evaluation_loop())
    yield
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    app = FastAPI(
        title="Network Pulse API",
        version=__version__,
        description="Ingests cell-site health metrics and reports which sites are unhealthy.",
        lifespan=lifespan,
    )
    # Only needed when the dashboard is served from a different origin
    # (the Vite proxy and the nginx container both make it same-origin).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "PUT", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        """Liveness probe: the process is up and serving requests."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    def readyz(db: Session = Depends(get_db)) -> dict[str, str]:
        """Readiness probe: the database is reachable."""
        try:
            db.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc
        return {"status": "ready"}

    app.include_router(health.router)
    app.include_router(sites.router)
    app.include_router(metrics.router)
    app.include_router(alerts.router)
    app.include_router(chaos.router)
    observability.install(app)
    return app


app = create_app()
