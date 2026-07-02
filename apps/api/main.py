from fastapi import FastAPI

from apps.api.routes.dashboard import router as dashboard_router
from apps.api.routes.health import router as health_router
from apps.api.routes.queries import router as queries_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Hawke XHS API", version="0.1.0")
    app.include_router(health_router)
    app.include_router(queries_router)
    app.include_router(dashboard_router)
    return app


app = create_app()
