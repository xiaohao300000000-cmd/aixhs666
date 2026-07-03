# AI Leads Business Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the minimum AI lead acquisition loop that turns existing and future XHS KET/PET posts/comments into actionable lead cards and enrichment tasks.

**Architecture:** Add persistent lead business tables above the existing raw data layer. A focused `services/lead_generation.py` service reads `contents`, `comments`, and `public_profiles`, reuses demand-chain rules, applies KET/PET lead scoring, writes idempotent leads/evidence/enrichment tasks, and is called by both a backfill CLI and Pipeline Runner. A new `/leads` product page and `/api/leads` endpoints expose lead cards instead of operational analytics.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, pytest, existing static HTML/CSS/JS pattern.

## Global Constraints

- Do not add CRM, Redis, Kafka, Kubernetes, or new infrastructure.
- `/ops` stays as an operations page and is not expanded for product usage.
- `/leads` becomes the product-facing lead acquisition page.
- Leads must be generated from existing historical `contents` and `comments`, not only future pipeline runs.
- Automatic generation must not overwrite manually handled or ignored leads.
- Every generated lead must have at least one explicit evidence row.
- `lead_id + task_type` enrichment tasks must be idempotent.
- KET/PET XHS is the first supported scenario.

---

### Task 1: Lead Persistence Model

**Files:**
- Create: `alembic/versions/0007_leads_business_objects.py`
- Modify: `storage/models.py`
- Test: `tests/test_lead_generation.py`

**Interfaces:**
- Produces ORM classes: `Lead`, `LeadEvidence`, `EnrichmentTask`.
- Produces database tables: `leads`, `lead_evidence`, `enrichment_tasks`.

- [ ] **Step 1: Write failing persistence test**

Add `tests/test_lead_generation.py` with an in-memory SQLite fixture and a test that inserts one profile, one lead, one evidence row, and one enrichment task. Assert uniqueness on `Lead.platform + Lead.public_profile_id` and `EnrichmentTask.lead_id + task_type`.

- [ ] **Step 2: Run test to verify failure**

Run: `.venv/bin/python -m pytest tests/test_lead_generation.py -q`

Expected: FAIL because `Lead` is not defined.

- [ ] **Step 3: Add ORM classes and Alembic migration**

Add lead fields required by the spec: `status`, `region_text`, `demand_type`, `product`, `intent_stage`, `intent_score`, `information_completeness`, `known_info_json`, `missing_info_json`, `recommended_next_step`, `first_seen_at`, `last_seen_at`, and relationships to profile/evidence/tasks.

- [ ] **Step 4: Run persistence test**

Run: `.venv/bin/python -m pytest tests/test_lead_generation.py -q`

Expected: PASS for persistence test.

### Task 2: Lead Generation Service

**Files:**
- Create: `services/lead_generation.py`
- Modify: `tests/test_lead_generation.py`

**Interfaces:**
- Produces `generate_leads_from_history(session: Session) -> LeadGenerationResult`.
- Produces `generate_leads_for_profiles(session: Session, profile_ids: set[int]) -> LeadGenerationResult`.
- Result fields: `leads_created`, `leads_updated`, `evidence_created`, `enrichment_tasks_created`, `qualified_leads`, `needs_enrichment_leads`.

- [ ] **Step 1: Write failing historical generation tests**

Tests must seed one profile with a KET/PET post and comment, run `generate_leads_from_history`, and assert exactly one lead, two evidence rows, merged known info, missing info, and status `needs_enrichment` or `qualified`.

- [ ] **Step 2: Write failing idempotency and manual-status tests**

Tests must run generation twice and assert no duplicate lead/evidence/task rows. A lead manually set to `handled` or `ignored` must keep that status after regeneration.

- [ ] **Step 3: Implement KET/PET rule engine**

Use existing demand-chain classifiers plus local keyword rules for product (`KET`, `PET`), demand type, stage, intent score, completeness, missing info, and recommended next step.

- [ ] **Step 4: Run service tests**

Run: `.venv/bin/python -m pytest tests/test_lead_generation.py -q`

Expected: PASS.

### Task 3: CLI and Pipeline Integration

**Files:**
- Modify: `apps/cli.py`
- Modify: `services/pipeline_runner.py`
- Test: `tests/test_pipeline_runner.py`
- Test: `tests/test_lead_generation.py`

**Interfaces:**
- CLI command: `python -m apps.cli --json leads-backfill`.
- Pipeline result section: `result_data["leads"]`.

- [ ] **Step 1: Write failing CLI test**

Use the existing CLI test pattern to call `leads-backfill` against a seeded database and assert JSON counts.

- [ ] **Step 2: Write failing Pipeline test**

Extend Pipeline Runner mock cycle assertions to require a `leads` result block with lead counts.

- [ ] **Step 3: Implement CLI command and Pipeline call**

Call `generate_leads_from_history` from CLI. In Pipeline Runner, call `generate_leads_for_profiles` after demand-chain analysis, using the current `PipelineScope.profile_ids`.

- [ ] **Step 4: Run integration tests**

Run: `.venv/bin/python -m pytest tests/test_lead_generation.py tests/test_pipeline_runner.py -q`

Expected: PASS.

### Task 4: Leads API

**Files:**
- Create: `apps/api/routes/leads.py`
- Modify: `apps/api/main.py`
- Test: `tests/test_leads_api.py`

**Interfaces:**
- `GET /api/leads/summary`
- `GET /api/leads`
- `POST /api/leads/backfill`
- `POST /api/leads/{lead_id}/status`

- [ ] **Step 1: Write failing API tests**

Tests must seed leads and assert summary buckets: today new, needs enrichment, qualified, handled. Tests must also assert status update to `handled` and `ignored`.

- [ ] **Step 2: Implement API route**

Return lead cards with profile identity, region, demand fields, scores, known/missing info, evidence, enrichment tasks, next step, and status.

- [ ] **Step 3: Register route**

Include the route in `apps/api/main.py`.

- [ ] **Step 4: Run API tests**

Run: `.venv/bin/python -m pytest tests/test_leads_api.py -q`

Expected: PASS.

### Task 5: Product Leads Page

**Files:**
- Create: `apps/api/templates/leads.html`
- Create: `apps/api/static/leads.css`
- Create: `apps/api/static/leads.js`
- Modify: `apps/api/routes/leads.py`
- Test: `tests/test_leads_api.py`

**Interfaces:**
- `GET /leads` returns the product page.
- `GET /leads/static/leads.css`
- `GET /leads/static/leads.js`

- [ ] **Step 1: Write failing page route test**

Assert `/leads` returns HTML containing the four lead buckets and does not redirect to `/ops`.

- [ ] **Step 2: Implement page and static assets**

Use a restrained dashboard layout with four product buckets: 今日新发现、待完善信息、可跟进客户、已处理客户.

- [ ] **Step 3: Run page tests**

Run: `.venv/bin/python -m pytest tests/test_leads_api.py -q`

Expected: PASS.

### Task 6: Documentation and Verification

**Files:**
- Modify: `README.md`
- Modify: `HANDOFF.md`
- Modify: `TASKS.md`
- Modify: `PROJECT_DASHBOARD.md`
- Modify: `docs/DATA_MODEL.md`

**Interfaces:**
- Documentation records `/leads`, lead objects, and the new acceptance metrics.

- [ ] **Step 1: Update docs**

Record that `/leads` is the product-facing page, `/ops` is operations-only, and the new acceptance metrics are lead count, evidence coverage, enrichment count, and qualified count.

- [ ] **Step 2: Run full automated tests**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests pass, with existing live tests skipped when credentials are absent.

- [ ] **Step 3: Run a local backfill command**

Run: `.venv/bin/python -m apps.cli --json leads-backfill`

Expected: JSON output containing lead generation counts. Counts may be zero only if the current local database has no matching KET/PET demand data.
