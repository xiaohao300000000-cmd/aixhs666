from __future__ import annotations

from fastapi import FastAPI

from runtime_env import load_dotenv


load_dotenv()

from apps.api.routes.operator_api import router as operator_api_router


def create_operator_gateway() -> FastAPI:
    app = FastAPI(
        title="AI Hawke Operator Gateway",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "operator-gateway"}

    app.include_router(operator_api_router)
    return app


app = create_operator_gateway()
