FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY apps ./apps
COPY collectors ./collectors
COPY scheduler ./scheduler
COPY storage ./storage
COPY intelligence ./intelligence
COPY integrations ./integrations

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && python -m playwright install --with-deps chromium

EXPOSE 8000

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
