# V0 Real Data Loop Report

Last updated: 2026-07-02

## Current True Status

The repository is currently a mock-backed backend prototype. Prior task dashboards report completion of T01-T22, but code inspection shows the real V0 loop is not complete.

## P0 Baseline

### Confirmed

- `collectors/mock.py` provides the active deterministic collection adapter used by existing tests.
- No `collectors/xiaohongshu/` implementation exists.
- `apps/worker/main.py` exits with `Worker scaffold is present; no jobs are implemented in T01.`
- Feishu modules construct review/signal payloads only; no complete delivery/callback persistence loop is present.
- Dashboard summary is currently a POST endpoint over caller-supplied metrics.
- Task claiming does not use PostgreSQL row locking.
- `discovery_relations` lacks a unique `(query_id, content_id)` constraint.

### Baseline Test Command

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Result on 2026-07-02:

```text
120 passed, 1 warning in 6.54s
```

Warning: Starlette deprecation warning from `fastapi.testclient` importing `httpx`.

## V01: Real Xiaohongshu Collector

Status: code complete; live page validation pending.

Implemented:

- Added `collectors/xiaohongshu/` with Playwright browser runtime, persistent profile config, centralized selectors, parser mapping, and explicit exception classes.
- Supported `search`, `get_content`, `list_comments`, and `get_profile` through the existing `PlatformAdapter` protocol objects.
- Added environment-based runtime directories for browser profile, snapshots, screenshots, timeout, and manual login window.
- Added parser tests with local saved page samples for search, content detail, comments, profile, login-required pages, selector failure, and missing optional fields.
- Added a `pytest.mark.live` live search test that is opt-in via `RUN_XHS_LIVE=1`.
- Added Playwright as a project dependency and recorded the dependency decision in `DECISIONS.md`.

Verification:

```bash
.venv/bin/python -m pytest tests/test_xiaohongshu_adapter.py -q
```

Result:

```text
10 passed, 1 skipped in 0.66s
```

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
130 passed, 1 skipped, 1 warning in 0.67s
```

```bash
.venv/bin/python -m pytest -m live -q
```

Result:

```text
1 skipped, 130 deselected, 1 warning in 0.26s
```

Not yet verified:

- Manual Xiaohongshu login.
- Live Xiaohongshu search result extraction.
- Live detail, comment, and profile extraction.

## V02: Worker Runtime Entry

Status: code complete; real long-running PostgreSQL worker validation pending.

Implemented:

- Added `python -m apps.worker` via `apps/worker/__main__.py`.
- Replaced scaffold `apps/worker/main.py` with a runnable `WorkerRunner`.
- Worker initializes database sessions, loads either real Xiaohongshu or mock adapter, claims tasks, dispatches by type, commits results, and catches single-task exceptions without exiting.
- Supported task dispatch for `search`, `collect_content`, `content_detail`, `comments`, `collect_comments`, `comment_collection`, `profile`, `collect_profile`, and `profile_collection`.
- Added partial task resume for search and comments using saved cursors.
- Added retry task handling through existing scheduler states.
- Added timed-out running task recovery before each claim.
- Added SIGINT and SIGTERM graceful stop hooks.
- Added CLI options: `--once`, `--worker-id`, `--poll-interval`, `--task-timeout-minutes`, `--platform`, and `--snapshot-root`.
- Added Worker service to `docker-compose.yml` using the same PostgreSQL service as the API.
- Updated container build to install Playwright Chromium dependencies for the worker image.

Verification:

```bash
.venv/bin/python -m pytest tests/test_worker_runtime.py tests/test_xhs_detail_collection.py -q
```

Result:

```text
11 passed in 0.26s
```

```bash
DATABASE_URL="sqlite+pysqlite:////tmp/aixhs-worker-entry.sqlite" WORKER_ADAPTER=mock .venv/bin/python -m apps.worker --once --worker-id entry-test
```

Result:

```text
exit code 0
```

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
136 passed, 1 skipped, 1 warning in 0.69s
```

Not yet verified:

- Long-running Worker against PostgreSQL.
- Two-worker PostgreSQL concurrent claiming. This belongs to V03.
- Real Xiaohongshu browser collection through Worker.

## V03: Database Concurrency And Idempotency

Status: code complete; PostgreSQL runtime validation pending due missing local PostgreSQL/Docker.

Implemented:

- `claim_next_task` now uses `FOR UPDATE SKIP LOCKED` when the active SQLAlchemy dialect is PostgreSQL.
- Added unique ORM constraint `uq_discovery_relations_query_id_content_id` on `(query_id, content_id)`.
- Added Alembic migration `0003_task_claiming_and_discovery_uniqueness`.
- PostgreSQL discovery relation ingestion now uses native `INSERT ... ON CONFLICT DO UPDATE` for `(query_id, content_id)`.
- Added tests asserting all required identity constraints:
  - `(platform, platform_content_id)`
  - `(platform, platform_comment_id)`
  - `(platform, platform_user_id)`
  - `(query_id, content_id)`
- Added PostgreSQL-only concurrency test for `claim_next_task` with two sessions and row-lock skipping.

Verification:

```bash
.venv/bin/python -m pytest tests/test_task_state_machine.py tests/test_storage_ingest.py tests/test_core_data_models.py tests/test_postgres_task_claiming.py -q
```

Result:

```text
24 passed, 1 skipped in 0.24s
```

The skipped test is the PostgreSQL-only concurrency test because `POSTGRES_TEST_DATABASE_URL` is not set.

```bash
.venv/bin/python -m alembic upgrade head --sql
```

Result:

```text
exit code 0
generated PostgreSQL SQL including:
ALTER TABLE discovery_relations ADD CONSTRAINT uq_discovery_relations_query_id_content_id UNIQUE (query_id, content_id);
```

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
137 passed, 2 skipped, 1 warning in 0.62s
```

```bash
.venv/bin/python -m pytest -m postgres -q
```

Result:

```text
1 skipped, 138 deselected, 1 warning in 0.26s
```

Not yet verified:

- Real `alembic upgrade head` against PostgreSQL.
- PostgreSQL two-worker concurrency test execution.
- PostgreSQL discovery relation conflict behavior under concurrent writes.

Environment blocker:

- `docker` command is not installed.
- `psql` and `pg_isready` are not installed.
- `localhost:5432` is not accepting connections.

## V04: Real Feishu Integration

Status: code implemented; real Feishu delivery not verified.

Implementation completed:

- Added `integrations/feishu/client.py` with environment-based settings, webhook transport, dry-run mode, timeout handling, retry handling, and masked secret errors.
- Added `integrations/feishu/webhook.py` for interactive-card webhook body construction, delivery helper, callback token validation, and isolated signature validation helper.
- Added `integrations/feishu/callbacks.py` for phrase review and signal alert callbacks.
- Supported phrase review actions: `approve`, `reject`, `convert_to_query`.
- Callback handling records database events and treats repeated callback IDs as idempotent duplicates.
- `convert_to_query` creates a new active seed query sourced from `feishu_phrase_review`.
- Added Feishu environment variables to `.env.example`.

Automated tests executed:

```bash
.venv/bin/python -m pytest tests/test_feishu_transport_callbacks.py tests/test_feishu_phrase_review.py tests/test_signal_freshness_alerts.py -q
```

Result:

```text
18 passed in 0.47s
```

Full regression:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
145 passed, 2 skipped, 1 warning in 0.90s
```

Not yet verified:

- Real Feishu webhook delivery, because no live Feishu credentials are configured.
- Real Feishu callback receipt through a public callback endpoint.
- Feishu production signature compatibility against a live callback request.

## V05: Database Dashboard Metrics

Status: code implemented and covered by local SQLite tests.

Implementation completed:

- Added `apps/api/dashboard_metrics.py` to build dashboard metrics directly from database tables.
- Added `GET /dashboard/summary` while keeping the existing `POST /dashboard/summary` offline/test payload path.
- Database-backed metrics currently include:
  - today's new content count,
  - today's new comment count,
  - today's new public profile count,
  - observed discovery count and duplicate content ratio,
  - per-query new content/discovery/task/failure counts,
  - overall task failure rate,
  - failed task ranking,
  - content/comment/profile field completeness,
  - phrase review status counts,
  - high-value signal event count,
  - pending phrase count,
  - latest successful collection time,
  - latest failure reason,
  - partial and retry task counts.

Automated tests executed:

```bash
.venv/bin/python -m pytest tests/test_data_dashboard.py -q
```

Result:

```text
6 passed, 1 warning in 0.28s
```

Not yet verified:

- `GET /dashboard/summary` against a real PostgreSQL database with live collected rows.
- Dashboard metrics after a real Xiaohongshu collection run.

## V06: Real Closed-Loop Validation

Status: not started.

## Risks

- Xiaohongshu page structure can change.
- Login state may expire or require manual intervention.
- Platform rate limiting may reduce collection volume.
- Selector failure must be explicit and observable.
- Feishu credentials may be unavailable, limiting verification to dry-run and mocked HTTP.
- Long-running browser and worker processes need resource monitoring.
- Public-data collection boundaries and compliance requirements must remain explicit.
