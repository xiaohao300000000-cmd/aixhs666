# V0 Real Data Loop Report

Last updated: 2026-07-02

## Current True Status

The repository now contains V0 real-loop code for Xiaohongshu collection, worker execution, database idempotency, Feishu transport/callback handling, database-backed dashboard metrics, PostgreSQL runtime diagnostics, Worker heartbeats, and a native `/ops` HTML console.

Validated on 2026-07-02:

- Homebrew PostgreSQL at `localhost:5432` is reachable.
- `alembic upgrade head` succeeded through revision `0004_worker_heartbeats`.
- `python -m scripts.check_runtime` passed.
- `POSTGRES_TEST_DATABASE_URL=... pytest -m postgres -q` passed with `1 passed`.
- `pytest -q` passed with `157 passed, 2 skipped`.
- `/ops`, `/ops/api/tasks`, `/ops/api/system`, and `GET /dashboard/summary` read the live PostgreSQL database.

Not validated:

- Docker Compose, because `docker` is not installed.
- Real Xiaohongshu data collection, because MediaCrawler waits for QR login/CDP Chrome and no usable logged-in session is available.
- Real Feishu delivery/callback, because credentials are not configured.
- Long-running Worker, dedupe with real content, interrupted real collection resume, and 100+ real result acceptance.

Live result file: `orchestration/e2e/live_postgres_result.json`.

Current live PostgreSQL counts: 5 queries, 5 search tasks, 0 contents, 0 comments, 0 public profiles, 0 discovery relations, 0 snapshots, 1 retry, 4 pending. This is not a completed real closed loop.

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

Status: partially verified. One real Xiaohongshu search run now succeeds after local Clash rule routing was changed; full PostgreSQL closed loop is still pending.

Automated verification executed:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
147 passed, 2 skipped, 1 warning in 0.96s
```

```bash
.venv/bin/python -m pytest -m live -q
```

Result:

```text
1 skipped, 148 deselected, 1 warning in 0.27s
```

The live test was skipped because live Xiaohongshu execution is opt-in and no live runtime variables/profile are configured.

Real Xiaohongshu navigation attempt on 2026-07-02:

```bash
RUN_XHS_LIVE=1 XHS_HEADLESS=false XHS_BROWSER_PROFILE_DIR=.runtime/xhs-profile XHS_SNAPSHOT_DIR=.runtime/snapshots XHS_SCREENSHOT_DIR=.runtime/screenshots XHS_MANUAL_LOGIN_TIMEOUT_MS=300000 .venv/bin/python -m pytest tests/test_xiaohongshu_adapter.py::test_live_xiaohongshu_search_requires_opt_in -q -s
```

Result:

```text
failed with XiaohongshuNetworkError:
Page.goto: net::ERR_CONNECTION_CLOSED at https://www.xiaohongshu.com/search_result?keyword=KET+...
screenshot=.runtime/screenshots/search-KET-没过怎么办.png
```

Network diagnosis:

```text
curl https://www.xiaohongshu.com/ failed with SSL_ERROR_SYSCALL.
DNS through the local environment returned fake-ip 198.18.0.111.
Clash Verge is configured with mixed-port 7897 and fake-ip DNS.
curl through 127.0.0.1:7897 still failed after CONNECT with SSL_ERROR_SYSCALL.
DoH resolved www.xiaohongshu.com to 43.159.95.157, but direct --resolve also failed with SSL_ERROR_SYSCALL.
```

Conclusion: the live browser reached the real Xiaohongshu URL path, but the current machine/network/proxy route closes the TLS connection before login or page parsing can begin. This is not evidence of successful live collection.

Network routing fix applied on 2026-07-02:

```text
Clash Verge runtime mode changed from global to rule.
Added DIRECT rules before other rules:
- DOMAIN-SUFFIX,xiaohongshu.com,DIRECT
- DOMAIN-SUFFIX,xiaohongshu.net,DIRECT
- DOMAIN-SUFFIX,xhscdn.com,DIRECT
- DOMAIN-SUFFIX,xhslink.com,DIRECT
- DOMAIN-SUFFIX,rednote.com,DIRECT
```

After reload, `curl -I -L --max-time 20 https://www.xiaohongshu.com/` returned an HTTP response instead of TLS failure.

Real Xiaohongshu search verification after routing fix:

```bash
RUN_XHS_LIVE=1 XHS_HEADLESS=false XHS_BROWSER_PROFILE_DIR=.runtime/xhs-profile XHS_SNAPSHOT_DIR=.runtime/snapshots XHS_SCREENSHOT_DIR=.runtime/screenshots XHS_MANUAL_LOGIN_TIMEOUT_MS=300000 .venv/bin/python -m pytest tests/test_xiaohongshu_adapter.py::test_live_xiaohongshu_search_requires_opt_in -q -s
```

Result:

```text
1 passed in 5.77s
```

Parsed live search sample:

```text
query: KET 没过怎么办
items parsed: 5
has_more: true
sample ids:
- 685b6d00000000001d00e06a
- 69d5eba9000000002102c15c
- 6975dffd000000000e03caa7
- 65d94daa00000000070245d0
- 6a45d7c00000000017008ff4
```

Code fixes made from the live run:

- Added `XHS_PROXY_SERVER` for per-browser proxy configuration.
- Changed search URL to `/search_result/` to avoid redirect instability.
- Made `networkidle` best-effort because Xiaohongshu keeps SPA/background requests open.
- Made screenshot capture best-effort so screenshot timeouts do not hide the original failure.
- Parsed appended captured network JSON payloads.
- Supported real `/api/sns/web/v2/search/notes` item wrappers where note ID is outside `note_card`.
- Waited explicitly for the search notes response before snapshotting.

Optional MediaCrawler backend added after live comparison:

```bash
WORKER_ADAPTER=mediacrawler python -m apps.worker --once
```

The adapter lives in `collectors/mediacrawler/` and runs the vendored MediaCrawler source under `third_party/MediaCrawler` via `MEDIACRAWLER_HOME`.
It reads MediaCrawler JSONL outputs and maps them into the existing `PlatformAdapter` objects.
MediaCrawler search mode fetches search results, note details, and optional comments in one subprocess run, so the adapter caches the outputs for later detail/comment tasks.
Sensitive `xsec_token` and cookie-like values are redacted from adapter logs, and normalized note URLs do not include `xsec_token`.

Local comparison run on 2026-07-02:

```text
keyword: KET 没过怎么办
MediaCrawler output: 20 notes, 60 first-level comments
runtime: 136.66 seconds
content completeness: all core fields present; tag_list present on 16/20 notes
comment completeness: all core first-level comment fields present
```

Adapter integration smoke after wiring `collectors/mediacrawler/`:

```text
MEDIACRAWLER_GET_COMMENTS=false adapter.search("KET 没过怎么办", limit=20)
result: 20 search items returned
first item: 6a37587e00000000210080ee / 我的口语有救了‼️ / 87 comments
```

The same smoke also passed with the default vendored path `third_party/MediaCrawler`.

Cached conversion verification using the full MediaCrawler run:

```text
cached detail: 6a37587e00000000210080ee, body present, 9 tags, 1 image URL
cached comments: 3 comments returned for first note
```

Important boundary: this backend depends on MediaCrawler's own implementation and local login state. It is optional and does not change the default `WORKER_ADAPTER=xiaohongshu` path.

```bash
.venv/bin/python -m pytest -m postgres -q
```

Result:

```text
1 skipped, 148 deselected, 1 warning in 0.26s
```

The PostgreSQL concurrency test was skipped because `POSTGRES_TEST_DATABASE_URL` is not configured.

```bash
.venv/bin/python -m alembic upgrade head
```

Result:

```text
failed: connection to localhost:5432 refused
```

This is an environment failure: the default database URL points to PostgreSQL on localhost, but no PostgreSQL server is running.

```bash
DATABASE_URL=sqlite+pysqlite:////tmp/aixhs-v06-alembic-batch.sqlite .venv/bin/python -m alembic upgrade head
```

Result:

```text
exit code 0
```

This verifies the migration chain can run locally on SQLite after changing migration 0003 to Alembic batch mode. It does not replace the required PostgreSQL upgrade verification.

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
docker compose up
```

Result:

```text
failed: docker: command not found
```

Environment checks:

```text
DATABASE_URL unset in shell; settings fall back to localhost PostgreSQL.
POSTGRES_TEST_DATABASE_URL unset.
XHS_BROWSER_PROFILE_DIR unset.
FEISHU_ENABLED unset.
FEISHU_WEBHOOK_URL unset.
FEISHU_APP_ID unset.
FEISHU_APP_SECRET unset.
FEISHU_VERIFICATION_TOKEN unset.
FEISHU_ENCRYPT_KEY unset.
docker command not installed.
psql command not installed.
localhost:5432 is not accepting PostgreSQL connections.
```

Real-data validation metrics:

```text
query seed count: 0 live-created in this environment
real posts/search results collected: 0
real comments collected: 0
real public profiles collected: 0
duplicate contents observed in live run: not verified
duplicate discovery relations observed in live run: not verified
failed task count in live run: not verified
partial/retry count in live run: not verified
Feishu send result: dry-run/mocked tests only; no real send
database dashboard live result: not verified against PostgreSQL/live collected rows
```

Required real closed-loop steps not completed:

- Creating the five seed queries in PostgreSQL.
- Running the real Xiaohongshu worker after manual login.
- Collecting at least 100 real posts/search results.
- Collecting real detail/comment/profile data.
- Forcing and recovering from a worker interruption against PostgreSQL.
- Re-running the same query batch and measuring real dedupe behavior.
- Verifying two workers do not claim the same PostgreSQL task.
- Sending a real Feishu alert.
- Reading dashboard metrics from a PostgreSQL database populated by real Xiaohongshu rows.

## Risks

- Xiaohongshu page structure can change.
- Login state may expire or require manual intervention.
- Platform rate limiting may reduce collection volume.
- Selector failure must be explicit and observable.
- Feishu credentials may be unavailable, limiting verification to dry-run and mocked HTTP.
- Long-running browser and worker processes need resource monitoring.
- Public-data collection boundaries and compliance requirements must remain explicit.
- PostgreSQL migration and concurrency behavior still need to be executed against a real PostgreSQL service.
- The current local machine cannot run `docker compose up` because Docker is not installed or not on PATH.
