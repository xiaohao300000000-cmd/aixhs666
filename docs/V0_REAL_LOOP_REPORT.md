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

Status: not started.

## V04: Real Feishu Integration

Status: not started.

## V05: Database Dashboard Metrics

Status: not started.

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
