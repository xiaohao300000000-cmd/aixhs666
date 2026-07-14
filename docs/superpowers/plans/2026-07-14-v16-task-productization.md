# V16 Feishu Task Center and Skill Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one operational Feishu task-center Skill, `screen_historical_leads`, with persistent runs/events, preview, queued Worker execution, progress, cancellation, explicit retry, copy, same-card updates, result summary, and optional Base history sync.

**Architecture:** PostgreSQL `SkillRun` and `SkillRunEvent` are the product facts. A static Python Registry describes the Skill, `services/skill_runtime.py` executes checkpointed stages, and the existing CollectionTask/Worker layer only dispatches `skill_run_execute`. Feishu cards call a fast persistent callback service; DeepSeek, Campaign qualification, and AI Review Base synchronization run only in the Worker through direct Python services.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, FastAPI, Pydantic, pytest, Feishu IM/OpenAPI, existing PostgreSQL task scheduler.

## Global Constraints

- Work only on `feat/v16-task-productization`.
- Implement only `screen_historical_leads`.
- Do not access Xiaohongshu or construct comment/private-message senders.
- Do not run live selector probes or live sends.
- Do not invoke project CLI commands through subprocess.
- PostgreSQL is the fact source; Feishu cards/Base are projections.
- Preserve the existing system control panel as an administrator compatibility entry.
- Use TDD for every production behavior change.

---

### Task 1: Persist Skill Runs and Events

**Files:**
- Modify: `storage/models.py`
- Create: `alembic/versions/0016_skill_runs.py`
- Create: `tests/test_skill_models.py`
- Modify: `docs/DATA_MODEL.md`

**Interfaces:**
- Produces: `SkillRun`, `SkillRunEvent`, status fields, JSON facts, event sequence and callback idempotency constraints.

- [ ] Write tests that create a run with JSON parameters, append ordered events, reject duplicate `(run_id, sequence)`, reject duplicate non-null `event_key`, and cascade-delete events.
- [ ] Run `tests/test_skill_models.py` and verify model/import failures.
- [ ] Add `SkillRun` and `SkillRunEvent` models with typed SQLAlchemy fields and relationships exactly matching `docs/TASK_PRODUCTIZATION.md`.
- [ ] Add migration `0016_skill_runs` with indexes on run status/stage, unique idempotency key, unique event key, and FK/cascade rules.
- [ ] Run model tests and migration upgrade/downgrade tests already present in the repository.

### Task 2: Build the Static Registry and Reusable Screening Interfaces

**Files:**
- Create: `services/skill_registry.py`
- Create: `tests/test_skill_registry.py`
- Modify: `services/llm_lead_screening.py`
- Modify: `services/feishu_ai_review_sync.py`
- Modify: `tests/test_llm_lead_screening.py`
- Modify: `tests/test_feishu_ai_review_sync.py`

**Interfaces:**
- Produces: `SkillDefinition`, `ScreenHistoricalLeadsParameters`, `get_skill_definition()`, `list_skill_definitions()`, `list_campaign_options()`.
- Extends: `run_llm_lead_screening(..., campaign: CampaignConfig | None = None)`.
- Extends: `sync_feishu_ai_review_rows(..., screening_ids: set[int] | None = None)`.

- [ ] Write Registry tests for the single Skill, Chinese name, version, stages, parameter defaults, invalid enums, limit below 1/above 500, and unknown Campaign.
- [ ] Verify Registry tests fail because the module is absent.
- [ ] Implement immutable Python Registry definitions using Pydantic parameter validation and `configs/campaigns/*.json` loading.
- [ ] Add an LLM screening test proving an explicitly supplied Campaign overrides the environment/default Campaign while callers without the argument retain existing behavior.
- [ ] Change `_apply_default_qualification` to accept optional Campaign and pass it from `run_llm_lead_screening`.
- [ ] Add an AI Review sync test proving `screening_ids` excludes other eligible rows.
- [ ] Add the optional filter to `_eligible_screenings` and keep the existing unfiltered path unchanged.
- [ ] Run Registry, LLM screening, qualification, Campaign config, and Feishu sync tests.

### Task 3: Implement the Skill Runtime State Machine

**Files:**
- Create: `services/skill_runtime.py`
- Create: `tests/test_skill_runtime.py`

**Interfaces:**
- Produces: `create_skill_run`, `update_skill_run_parameters`, `preview_skill_run`, `queue_skill_run`, `execute_skill_run`, `request_skill_run_cancel`, `retry_skill_run`, `copy_skill_run`, `skill_run_result_view`.
- Consumes: Registry, `run_llm_lead_screening`, `sync_feishu_ai_review_rows`, scheduler `create_task`, and models from Task 1.

- [ ] Write parameter/preview tests proving preview queries local Content/Comment rows only and does not invoke the LLM client.
- [ ] Write state-transition tests for draft → previewed → queued → running → succeeded and invalid transitions.
- [ ] Write callback/idempotency-facing tests proving repeated queue calls create one `skill_run_execute` task.
- [ ] Write stage-event tests for created, previewed, queued, started, stage_started, progress and completed sequences.
- [ ] Write restart recovery tests with a checkpoint containing two candidates and `next_index=1`; verify execution resumes only the second candidate.
- [ ] Write explicit failure/retry tests: a failed run stays failed until `retry_skill_run`, then requeues once and increments `retry_count`.
- [ ] Write cancellation tests for draft/previewed/queued, cancel request during screen, and rejection during `sync_feishu`.
- [ ] Write result summary tests for processed, accepted, high intent, needs review, failed/skipped and Feishu sync counters.
- [ ] Implement transition guards, monotonically increasing event sequence, candidate preparation, per-item commit/checkpoint, cancel checks, non-interruptible sync, result summary and sanitized errors.
- [ ] Run `tests/test_skill_runtime.py` until all state and recovery contracts pass.

### Task 4: Dispatch Skill Runs Through the Existing Worker

**Files:**
- Create: `apps/worker/skill_run.py`
- Modify: `apps/worker/main.py`
- Modify: `tests/test_worker_runtime.py`

**Interfaces:**
- Produces: `SKILL_RUN_TASK_TYPES = {"skill_run_execute"}` and `run_skill_run_task(session, task, session_factory)`.
- Consumes: `execute_skill_run` from Task 3.

- [ ] Add Worker tests proving a queued run executes once, a resumed running run re-enters Runtime, malformed target IDs fail the CollectionTask, and Runtime failure marks the task failed without auto-retrying the Skill Run.
- [ ] Verify the new Worker tests fail because the task type is unsupported.
- [ ] Implement the focused task handler using existing `complete_task`/`fail_task` patterns and register it in `WorkerRunner._dispatch`.
- [ ] Run Worker and Skill Runtime tests.

### Task 5: Deliver the Feishu Task Center Card Loop

**Files:**
- Modify: `integrations/feishu/im.py`
- Create: `services/feishu_task_center.py`
- Modify: `apps/api/routes/feishu_callbacks.py`
- Modify: `apps/cli.py`
- Modify: `integrations/feishu/__init__.py`
- Create: `tests/test_feishu_task_center.py`
- Modify: `tests/test_feishu_transport_callbacks.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: catalog/form/preview/progress/failure/result card renderers; `send_task_center_card`; `apply_task_center_callback`; `FeishuIMClient.patch_interactive_message`.
- Adds CLI: `feishu-task-center --chat-id CHAT_ID` that directly calls the Python service.

- [ ] Add Feishu IM client tests for `PATCH /open-apis/im/v1/messages/{message_id}` with `content` as serialized complete card JSON and bot/user transport behavior.
- [ ] Add card rendering tests for catalog, parameter form, preview, queued/running progress, cancellable/non-cancellable states, failed/retry, completed result, view result and copy.
- [ ] Add callback tests for create, preview form submission, confirm, cancel, retry, copy, invalid token, message/chat mismatch, duplicate event ID and repeated confirm clicks.
- [ ] Verify callback tests fail before implementation.
- [ ] Implement `patch_interactive_message` using the official Feishu message patch API; preserve delayed token update for immediate callback views.
- [ ] Implement task-center card actions with stable names and complete Card 1.0 JSON.
- [ ] Implement callback application as short PostgreSQL transactions; confirm only queues a persistent run and returns `accepted` without constructing an LLM client.
- [ ] Update Worker-side card projection after each persisted Runtime event/status checkpoint using the bound `message_id`.
- [ ] Add CLI parser/handler that sends the catalog card without subprocess recursion.
- [ ] Run Feishu task-center, transport, existing review callback and CLI tests.

### Task 6: Add Optional Task Run History Projection

**Files:**
- Create: `services/feishu_skill_run_sync.py`
- Create: `tests/test_feishu_skill_run_sync.py`
- Modify: `services/skill_runtime.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `sync_skill_run_history(session, run, client=None)` and a stable Base field payload.

- [ ] Write tests for fields, create/update mapping, disabled/unconfigured skip, and isolated sync failure.
- [ ] Implement an optional `FEISHU_SKILL_RUN_TABLE_ID` projection using existing `FeishuBitableRecord` mappings and `FeishuBitableClient`.
- [ ] Call the projection after preview, queue, terminal status and copy; record failure in `feishu_sync_error` and an event without changing business status.
- [ ] Run history sync and Runtime tests.

### Task 7: Update Product Documentation and Project State

**Files:**
- Modify: `docs/PRD.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DATA_MODEL.md`
- Modify: `docs/ROADMAP.md`
- Modify: `README.md`
- Modify: `TASKS.md`
- Modify: `HANDOFF.md`
- Modify: `PROJECT_DASHBOARD.md`
- Modify: `DECISIONS.md`
- Create: `docs/reports/V16_TASK_PRODUCTIZATION_VERIFICATION.md`

**Interfaces:**
- Produces: user-facing boundaries, operational setup, exact automated evidence, per-file summary and real acceptance steps.

- [ ] Document Skill/Run/Event/Card/Pipeline/CollectionTask boundaries and the system-control-panel compatibility role.
- [ ] Add V16 scope/status to PRD, architecture, data model, roadmap, tasks, dashboard and handoff.
- [ ] Record the decision that Skill Run is the product fact and CollectionTask is only execution delivery.
- [ ] Write real acceptance steps: migrate DB, configure Feishu callback/chat/Base, send catalog card, create/preview/confirm, observe same-card progress, verify result counts, cancel a safe run, retry a forced failure, copy a run, and verify no Xiaohongshu network activity.
- [ ] Include a per-file change summary in the verification report.

### Task 8: Complete Repository Verification and Push the Feature Branch

**Files:**
- Verify: complete repository.

**Interfaces:**
- Produces: a tested and pushed `feat/v16-task-productization` branch.

- [ ] Run focused Skill/Feishu/Worker tests.
- [ ] Run `.venv/bin/python -m pytest -q` and record exact counts.
- [ ] Run `git diff --check` and Python compile checks for new modules.
- [ ] Scan changed files for credentials, live targets, Xiaohongshu sender imports and subprocess-based project CLI calls.
- [ ] Update HANDOFF, dashboard and verification report with fresh evidence.
- [ ] Commit with a V16 feature message and push `feat/v16-task-productization` to origin.
