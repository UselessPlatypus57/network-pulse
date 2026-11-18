from fastapi import FastAPI

from app import __version__


def create_app() -> FastAPI:
    app = FastAPI(
        title="Network Pulse API",
        version=__version__,
        description="Ingests cell-site health metrics and reports which sites are unhealthy.",
    )

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        """Liveness probe: the process is up and serving requests."""
        return {"status": "ok"}

    return app


app = create_app()
