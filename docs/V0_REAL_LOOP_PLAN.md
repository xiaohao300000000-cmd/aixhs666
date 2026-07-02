# V0 Real Data Loop Plan

Last updated: 2026-07-02

## Scope

This plan replaces the previous mock-only completion framing with a concrete V0 target: a runnable real-data loop for Xiaohongshu public data, PostgreSQL persistence, resumable collection tasks, Feishu delivery, and database-backed dashboard metrics.

This V0 explicitly excludes second-platform evaluation, private messaging, automated comments, CRM, complex agent orchestration, and new scoring concepts.

## Baseline Facts Confirmed From Code

1. Current collection tests and workflows mainly use `MockPlatformAdapter` in `collectors/mock.py`.
2. There is no usable `XiaohongshuAdapter`; no `collectors/xiaohongshu/` package exists yet.
3. `apps/worker/main.py` is a scaffold that exits immediately, so there is no continuously runnable Worker entry.
4. Feishu code currently builds review and signal payloads; it does not provide a complete real send and callback persistence loop.
5. `apps/api/routes/dashboard.py` exposes `POST /dashboard/summary` and computes from caller-provided metrics, not direct database statistics.
6. `scheduler.task_state_machine.claim_next_task` uses a normal SELECT and can let multiple PostgreSQL workers claim the same task under concurrency.
7. `discovery_relations` has an index on `(query_id, discovered_at)` but no unique database constraint on `(query_id, content_id)`.

## Work Items

### V01: Real Xiaohongshu Collector

Status: code complete; live Xiaohongshu validation pending.

Implement `collectors/xiaohongshu/` with Playwright-based browser access, persistent login profile, explicit login and selector errors, parser tests using saved real-page samples, and live tests marked separately.

### V02: Worker Runtime Entry

Status: code complete; long-running PostgreSQL worker validation pending.

Implement `python -m apps.worker` with database Session setup, adapter loading, task polling, task-type dispatch, partial/retry handling, timeout recovery, graceful shutdown, configurable worker ID, polling interval, and once mode.

### V03: Database Concurrency And Idempotency

Status: code complete; PostgreSQL runtime concurrency validation pending.

Make PostgreSQL task claiming safe with `FOR UPDATE SKIP LOCKED`, add a unique constraint for `discovery_relations(query_id, content_id)`, use database-backed upsert/conflict handling, and add PostgreSQL concurrency tests.

### V04: Real Feishu Integration

Status: code complete; real Feishu delivery and callback validation pending.

Add Feishu transport and callback handling on top of existing payload builders, including webhook/app delivery, retries, timeouts, dry-run, secret masking, signature/verification helpers, and idempotent review callbacks.

### V05: Database Dashboard Metrics

Status: code complete; PostgreSQL/live-data dashboard validation pending.

Add `GET /dashboard/summary` backed directly by PostgreSQL statistics for collection volume, duplication, query output, task success/failure, field completeness, high-value signals, phrase review state, and latest collection status.

### V06: Real Closed-Loop Validation

Status: blocked by missing local Docker/PostgreSQL, missing Feishu credentials, and missing configured Xiaohongshu live login/profile.

Run a real Xiaohongshu validation with five education seed queries, at least 100 real search results/posts, partial detail/comment/profile collection, forced worker interruption and recovery, repeated collection dedupe checks, dashboard validation, and Feishu real send or documented dry-run.

## Evidence Rules

- Mock tests cannot be used as evidence of live collection.
- Payload construction cannot be used as evidence of Feishu delivery.
- SQLite tests cannot be used as evidence of PostgreSQL worker concurrency.
- Unverified live steps must be recorded as risks, not marked complete.
