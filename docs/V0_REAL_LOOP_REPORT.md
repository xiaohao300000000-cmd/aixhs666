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

Status: not started.

## V02: Worker Runtime Entry

Status: not started.

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
