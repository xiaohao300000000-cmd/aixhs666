from fastapi import FastAPI

from apps.api.routes.dashboard import router as dashboard_router
from apps.api.routes.feishu_callbacks import router as feishu_callbacks_router
from apps.api.routes.health import router as health_router
from apps.api.routes.leads import router as leads_router
from apps.api.routes.ops import router as ops_router
from apps.api.routes.ops_api import router as ops_api_router
from apps.api.routes.queries import router as queries_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Hawke XHS API", version="0.1.0")
    app.include_router(health_router)
    app.include_router(queries_router)
    app.include_router(dashboard_router)
    app.include_router(leads_router)
    app.include_router(ops_router)
    app.include_router(ops_api_router)
    app.include_router(feishu_callbacks_router)
    return app


app = create_app()
