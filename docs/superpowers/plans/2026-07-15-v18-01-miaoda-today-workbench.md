# V18-01 Miaoda Today Workbench Implementation Plan

> **Required subskill:** Use `superpowers:executing-plans` to implement this plan task by task in isolated git worktrees.

**Goal:** Publish a Feishu-hosted Miaoda operations console whose home page gives the operator one reliable place to see today's lead-review workload, skill-run progress, task failures, worker health, and the next recommended action.

**Architecture:** Keep PostgreSQL and the existing FastAPI service as the system of record. Add one authenticated, read-only operator aggregation endpoint to FastAPI. The Miaoda NestJS server acts as a BFF and keeps the backend service token server-side. The React client calls only same-origin Miaoda endpoints and renders an operations-first workbench with explicit loading, empty, degraded, and error states.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, pytest, React 19, TypeScript 5.9, React Router, TanStack Query, NestJS 10, Axios, Tailwind CSS 4, Jest, Miaoda full-stack runtime.

**Global Constraints:**

- Do not add a new database table or migration in this task.
- Do not change existing collection, screening, Feishu callback, or worker behavior.
- Reuse `OPS_TOKEN`; never expose it to the browser or commit it.
- Treat PostgreSQL as the source of truth and calculate the workbench response from existing models.
- The UI must remain useful when the backend is unavailable by showing a clear degraded state and retry action; it must not silently substitute fake production data.
- Implement only `V18-01`; lead-review writes, task creation, Campaign editing, and Founder Copilot automation remain later tasks.

## Task 1: Register V18-01 as the active project task

**Files:**

- Modify: `TASKS.md`
- Modify: `PROJECT_DASHBOARD.md`
- Modify: `DECISIONS.md`

- [ ] **Step 1: Add the task definition**

Add a `V18 妙搭运营控制台` section with `V18-01` as the only active task and later tasks listed as pending follow-ups.

- [ ] **Step 2: Record the architecture decision**

Document that Miaoda is the presentation/BFF layer while FastAPI/PostgreSQL remain the business and data source-of-truth layers.

- [ ] **Step 3: Verify documentation formatting**

Run:

```bash
git diff --check
```

Expected: exit code `0` and no output.

- [ ] **Step 4: Commit the task registration**

```bash
git add TASKS.md PROJECT_DASHBOARD.md DECISIONS.md docs/superpowers/specs/2026-07-15-feishu-miaoda-operations-console-design.md docs/superpowers/plans/2026-07-15-v18-01-miaoda-today-workbench.md
git commit -m "docs: define miaoda operations console v18"
```

## Task 2: Add a tested operator workbench service

**Files:**

- Create: `services/operator_workbench.py`
- Create: `tests/test_operator_workbench.py`

- [ ] **Step 1: Write failing aggregation tests**

Cover these cases with existing model fixtures or locally created rows:

```python
def test_build_operator_workbench_counts_review_queue_and_runs(session): ...
def test_build_operator_workbench_reports_stale_worker_and_failed_tasks(session): ...
def test_build_operator_workbench_returns_empty_sections_for_empty_database(session): ...
```

The response contract must contain:

```python
{
    "generated_at": "...",
    "attention": {
        "review_queue": 0,
        "running_skills": 0,
        "failed_tasks": 0,
        "stale_workers": 0,
    },
    "lead_queue": [...],
    "skill_runs": [...],
    "task_failures": [...],
    "workers": [...],
    "next_action": {
        "kind": "review_leads|inspect_failure|monitor_run|none",
        "title": "...",
        "description": "...",
        "target": "...",
    },
}
```

- [ ] **Step 2: Run the tests to prove RED**

Run:

```bash
pytest tests/test_operator_workbench.py -q
```

Expected: failure because `services.operator_workbench` does not exist.

- [ ] **Step 3: Implement the minimal aggregation service**

Use SQLAlchemy queries against `Lead`, `LeadEvidence`, `SkillRun`, `CollectionTask`, and `WorkerHeartbeat`. Limit each detail list to ten rows, use UTC timestamps, and centralize serialization helpers in the new service.

Queue rules for this task:

- Lead review queue: `Lead.status` in `new`, `needs_enrichment`, `watch`, or `information_insufficient`.
- Running skill: `SkillRun.status` in `queued`, `running`, or `cancelling`.
- Failed task: `CollectionTask.status == "failed"`.
- Stale worker: heartbeat older than five minutes.
- Recommended action priority: failed task, review queue, running skill, then none.

- [ ] **Step 4: Run the tests to prove GREEN**

Run:

```bash
pytest tests/test_operator_workbench.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the service**

```bash
git add services/operator_workbench.py tests/test_operator_workbench.py
git commit -m "feat: aggregate operator workbench data"
```

## Task 3: Expose the authenticated FastAPI endpoint

**Files:**

- Create: `apps/api/routes/operator_api.py`
- Modify: `apps/api/main.py`
- Create: `tests/test_operator_api.py`

- [ ] **Step 1: Write failing API contract tests**

Add tests for:

```python
def test_operator_workbench_rejects_missing_token(client, monkeypatch): ...
def test_operator_workbench_rejects_wrong_token(client, monkeypatch): ...
def test_operator_workbench_returns_aggregate(client, monkeypatch): ...
```

The endpoint is `GET /operator/api/workbench` and accepts `Authorization: Bearer <OPS_TOKEN>` plus the existing `X-Ops-Token` compatibility header.

- [ ] **Step 2: Run the tests to prove RED**

Run:

```bash
pytest tests/test_operator_api.py -q
```

Expected: `404` or import failure because the router does not exist.

- [ ] **Step 3: Implement the route and shared auth dependency**

Extract or reuse token validation without weakening `/ops/api` writes. Return `503` with a structured detail if `OPS_TOKEN` is not configured. Include the router in `create_app()`.

- [ ] **Step 4: Run focused and regression tests**

Run:

```bash
pytest tests/test_operator_api.py tests/test_operator_workbench.py tests/test_ops_console.py tests/test_leads_api.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the API**

```bash
git add apps/api/main.py apps/api/routes/operator_api.py tests/test_operator_api.py
git commit -m "feat: expose operator workbench api"
```

## Task 4: Add the Miaoda BFF proxy

**Files:**

- Create: `/Users/xiaohao30000/aixhs666-console/server/modules/operator/operator.module.ts`
- Create: `/Users/xiaohao30000/aixhs666-console/server/modules/operator/operator.controller.ts`
- Create: `/Users/xiaohao30000/aixhs666-console/server/modules/operator/operator.service.ts`
- Create: `/Users/xiaohao30000/aixhs666-console/server/modules/operator/operator.service.spec.ts`
- Modify: `/Users/xiaohao30000/aixhs666-console/server/app.module.ts`
- Modify: `/Users/xiaohao30000/aixhs666-console/.env.example`

- [ ] **Step 1: Write failing NestJS service tests**

Test that the service:

- calls `${OPERATOR_API_BASE_URL}/operator/api/workbench`;
- sends the token only from `OPERATOR_API_TOKEN`;
- never returns the token in payloads or errors;
- maps connection errors to a stable `503` response.

- [ ] **Step 2: Run the test to prove RED**

Run:

```bash
npm test -- --runInBand server/modules/operator/operator.service.spec.ts
```

Expected: failure because the operator module does not exist.

- [ ] **Step 3: Implement the BFF**

Expose only `GET /api/operator/workbench`. Use `@nestjs/axios` and `ConfigModule`; validate both required environment variables at request time so the app can still render a configuration error page.

- [ ] **Step 4: Run server verification**

Run:

```bash
npm test -- --runInBand server/modules/operator/operator.service.spec.ts
npm run type:check:server
```

Expected: tests and type checking pass.

- [ ] **Step 5: Commit the BFF**

```bash
git add server/modules/operator server/app.module.ts .env.example
git commit -m "feat: add operator console bff"
```

## Task 5: Build the operations-first React workbench

**Files:**

- Modify: `/Users/xiaohao30000/aixhs666-console/client/src/app.tsx`
- Modify: `/Users/xiaohao30000/aixhs666-console/client/src/components/Layout.tsx`
- Modify: `/Users/xiaohao30000/aixhs666-console/client/src/index.tsx`
- Modify: `/Users/xiaohao30000/aixhs666-console/client/src/index.css`
- Create: `/Users/xiaohao30000/aixhs666-console/client/src/api/operator.ts`
- Create: `/Users/xiaohao30000/aixhs666-console/client/src/types/operator.ts`
- Create: `/Users/xiaohao30000/aixhs666-console/client/src/components/operator/AppShell.tsx`
- Create: `/Users/xiaohao30000/aixhs666-console/client/src/components/operator/AttentionCard.tsx`
- Create: `/Users/xiaohao30000/aixhs666-console/client/src/components/operator/LeadQueue.tsx`
- Create: `/Users/xiaohao30000/aixhs666-console/client/src/components/operator/RunProgress.tsx`
- Create: `/Users/xiaohao30000/aixhs666-console/client/src/components/operator/SystemPulse.tsx`
- Create: `/Users/xiaohao30000/aixhs666-console/client/src/pages/TodayWorkbenchPage.tsx`
- Create: `/Users/xiaohao30000/aixhs666-console/test/unit/operator-view-model.spec.ts`
- Create: `/Users/xiaohao30000/aixhs666-console/client/src/features/operator/operator-view-model.ts`

- [ ] **Step 1: Write failing view-model tests**

Test deterministic presentation rules without adding a browser test dependency:

```typescript
it('prioritizes failed tasks as urgent attention');
it('formats an empty workbench without fake metrics');
it('marks stale workers as degraded');
```

- [ ] **Step 2: Run the tests to prove RED**

Run:

```bash
npm test -- --runInBand test/unit/operator-view-model.spec.ts
```

Expected: failure because the view-model module does not exist.

- [ ] **Step 3: Implement the view model and API client**

Use `axiosForBackend` for same-origin calls and TanStack Query with a 30-second refetch interval. Keep API types explicit and avoid `any`.

- [ ] **Step 4: Implement the approved visual hierarchy**

Build the approved combination of concepts 2 and 3:

- left navigation for 今日工作台、线索审核、任务中心、Campaign 中心、系统健康;
- top status strip with live/degraded state and last refresh;
- first row of attention cards;
- main two-column area with lead-review queue and next-action/evidence panel;
- lower rows for skill progress, failed tasks, and worker health;
- neutral dark-blue operational shell, warm white content surface, compact cards, strong status color semantics;
- responsive tablet layout without horizontal page scrolling.

For unimplemented navigation destinations, render an explicit “将在后续阶段开放” panel instead of dead links.

- [ ] **Step 5: Implement loading, empty, degraded, and error states**

The degraded state must preserve navigation and explain whether the missing configuration is `OPERATOR_API_BASE_URL`, `OPERATOR_API_TOKEN`, or backend reachability, without displaying secret values.

- [ ] **Step 6: Run client verification**

Run:

```bash
npm test -- --runInBand test/unit/operator-view-model.spec.ts
npm run type:check:client
npm run build:client
```

Expected: all commands pass.

- [ ] **Step 7: Commit the client**

```bash
git add client test/unit/operator-view-model.spec.ts
git commit -m "feat: build today operations workbench"
```

## Task 6: Integrate, document, and publish

**Files:**

- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `HANDOFF.md`
- Modify: `TASKS.md`
- Modify: `PROJECT_DASHBOARD.md`
- Modify: `/Users/xiaohao30000/aixhs666-console/README.md`

- [ ] **Step 1: Configure local integration without committing secrets**

Set `OPERATOR_API_BASE_URL` and `OPERATOR_API_TOKEN` in the Miaoda app's local `.env.local`. Start FastAPI and Miaoda locally.

- [ ] **Step 2: Run browser acceptance**

Verify in the in-app browser:

- application opens without console errors;
- live counts match the backend response;
- refresh works;
- backend shutdown produces the designed degraded state;
- narrow viewport remains usable;
- no token appears in browser network response bodies or rendered HTML.

- [ ] **Step 3: Run complete verification**

Backend:

```bash
pytest -q
python -m compileall apps services storage
git diff --check
```

Miaoda:

```bash
npm test -- --runInBand
npm run type:check
npm run lint
npm run build
git diff --check
```

Expected: all commands pass, aside from explicitly documented pre-existing warnings.

- [ ] **Step 4: Update project documentation**

Mark only `V18-01` complete. Record the published URL, environment-variable contract, architecture boundary, verification evidence, known dependency on backend reachability, and next recommended task `V18-02` lead-review actions.

- [ ] **Step 5: Commit and push both repositories**

Backend:

```bash
git add README.md docs/ARCHITECTURE.md HANDOFF.md TASKS.md PROJECT_DASHBOARD.md
git commit -m "docs: hand off miaoda workbench"
git push origin HEAD
```

Miaoda:

```bash
git add README.md
git commit -m "docs: document operator console setup"
git push origin sprint/default
```

- [ ] **Step 6: Publish the Miaoda application**

Use `lark-cli apps +release-create app_17a4790srtt`, monitor the release to completion, and capture the shareable application URL. Do not publish if required secrets cannot be configured safely or the backend has no stable reachable endpoint; in that case publish only after documenting the precise blocker.

