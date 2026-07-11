import os
from functools import lru_cache

from pydantic import BaseModel, Field


DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://education_demand:change_me@localhost:5432/education_demand"
)


class Settings(BaseModel):
    app_env: str = Field(default="development")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    database_url: str = Field(default=DEFAULT_DATABASE_URL)
    feishu_customer_followup_app_token: str | None = None
    feishu_customer_followup_table_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        feishu_customer_followup_app_token=os.getenv("FEISHU_CUSTOMER_FOLLOWUP_APP_TOKEN") or None,
        feishu_customer_followup_table_id=os.getenv("FEISHU_CUSTOMER_FOLLOWUP_TABLE_ID") or None,
    )
