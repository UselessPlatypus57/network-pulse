from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.db import init_db
from app.routers import metrics, sites


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Network Pulse API",
        version=__version__,
        description="Ingests cell-site health metrics and reports which sites are unhealthy.",
        lifespan=lifespan,
    )

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        """Liveness probe: the process is up and serving requests."""
        return {"status": "ok"}

    app.include_router(sites.router)
    app.include_router(metrics.router)
    return app


app = create_app()
