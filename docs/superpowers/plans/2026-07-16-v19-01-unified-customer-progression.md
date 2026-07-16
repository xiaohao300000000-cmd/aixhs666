# V19-01 Unified Customer Progression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Miaoda and Feishu review actions produce the same auditable customer progression result, with a visible “推进为客户” action and explicit next-step feedback.

**Architecture:** Add a focused customer-progression service that owns review state changes, customer follow-up facts, idempotency, and timeline events. Operator API and Feishu callbacks call this service instead of independently mutating review state; Miaoda consumes the structured result and shows concrete consequences.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, pytest, React 18, TypeScript, Jest, NestJS BFF.

## Global Constraints

- PostgreSQL and the Python business backend remain the only source of truth.
- Miaoda, Feishu cards, and future Base actions must call the same business command.
- “有效” and “进入跟进” become one business action: “推进为客户”.
- External sending remains human-confirmed and is not added in V19-01.
- Every write is idempotent and records an auditable timeline event.
- Do not expose Operator tokens or add direct database access to Miaoda.
- Do not modify unrelated collection, private-message, Base CRM, or scheduling behavior.

---

### Task 1: Persist Customer Timeline Events

**Files:**
- Modify: `storage/models.py`
- Create: `alembic/versions/0017_customer_timeline_events.py`
- Create: `tests/test_customer_timeline_models.py`

**Interfaces:**
- Produces: `CustomerTimelineEvent(lead_id, event_key, event_type, actor_id, data_json, occurred_at)` with unique `event_key`.
- Consumes: existing `Lead.id` and SQLAlchemy `Base`.

- [ ] **Step 1: Write the failing model test**

```python
def test_customer_timeline_event_key_is_idempotent(factory):
    with factory() as session:
        session.add_all([
            CustomerTimelineEvent(lead_id=1, event_key="review:event-1", event_type="candidate_promoted"),
            CustomerTimelineEvent(lead_id=1, event_key="review:event-1", event_type="candidate_promoted"),
        ])
        with pytest.raises(IntegrityError):
            session.commit()
```

- [ ] **Step 2: Run the model test and verify failure**

Run: `pytest tests/test_customer_timeline_models.py -q`  
Expected: FAIL because `CustomerTimelineEvent` does not exist.

- [ ] **Step 3: Add the model and migration**

```python
class CustomerTimelineEvent(Base):
    __tablename__ = "customer_timeline_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_customer_timeline_events_event_key"),
        Index("ix_customer_timeline_events_lead_occurred", "lead_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255))
    data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **Step 4: Run model and migration tests**

Run: `pytest tests/test_customer_timeline_models.py tests/test_migrations.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add storage/models.py alembic/versions/0017_customer_timeline_events.py tests/test_customer_timeline_models.py
git commit -m "feat: add customer timeline events"
```

### Task 2: Implement Unified Progression Commands

**Files:**
- Create: `services/customer_progression.py`
- Create: `tests/test_customer_progression.py`
- Modify: `services/operator_leads.py`

**Interfaces:**
- Produces: `progress_operator_lead(session, lead_id, *, action, reason, reviewer_id, idempotency_key, defer_until=None) -> CustomerProgressionResult`.
- Produces: `promote_screening_customer(session, screening_id, *, reviewer_id, idempotency_key) -> CustomerProgressionResult`.
- Produces actions: `promote`, `defer`, `reject`; accepts legacy aliases only at API boundaries.
- Consumes: `Lead`, latest `LeadScreeningResult`, and `CustomerTimelineEvent`.

- [ ] **Step 1: Write failing command tests**

```python
def test_promote_sets_customer_facts_and_timeline(factory, lead):
    with factory() as session:
        result = progress_operator_lead(
            session,
            lead.id,
            action="promote",
            reason="需求明确",
            reviewer_id="operator-1",
            idempotency_key="review-1",
        )
        assert result.customer_id == lead.id
        assert result.customer_stage == "awaiting_first_contact"
        assert result.next_action == "prepare_public_reply"
        assert result.timeline_event_type == "candidate_promoted"


def test_duplicate_progression_returns_same_event(factory, lead):
    first = _promote(factory, lead.id, "review-1")
    second = _promote(factory, lead.id, "review-1")
    assert second.timeline_event_id == first.timeline_event_id
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_customer_progression.py -q`  
Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement minimal command service**

```python
@dataclass(frozen=True)
class CustomerProgressionResult:
    customer_id: int
    customer_stage: str
    next_action: str
    timeline_event_id: int
    timeline_event_type: str
    screening_id: int | None
    idempotent_replay: bool


def progress_operator_lead(...):
    # validate action/reason/defer_until
    # return existing event for the same event_key
    # update Lead and latest Screening in one transaction
    # append one CustomerTimelineEvent
    # flush and return structured consequences
```

State mapping:

```python
PROGRESSION_STATES = {
    "promote": ("qualified", "valid", "pending", "awaiting_first_contact", "prepare_public_reply"),
    "defer": ("watch", "watch", "deferred", "deferred", "wait_for_reactivation"),
    "reject": ("ignored", "invalid", None, "invalid", "none"),
}
```

- [ ] **Step 4: Keep read/query helpers in `operator_leads.py` and delegate writes**

`review_operator_lead()` remains a compatibility wrapper that maps legacy actions and calls `progress_operator_lead()`; it must not duplicate state mutations.

- [ ] **Step 5: Run progression and existing lead tests**

Run: `pytest tests/test_customer_progression.py tests/test_operator_leads.py -q`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/customer_progression.py services/operator_leads.py tests/test_customer_progression.py tests/test_operator_leads.py
git commit -m "feat: unify customer progression commands"
```

### Task 3: Route Operator API Through Progression Service

**Files:**
- Modify: `apps/api/routes/operator_api.py`
- Modify: `tests/test_operator_api.py`

**Interfaces:**
- Consumes: `progress_operator_lead()`.
- Produces request fields: `action`, `reason`, `reviewer_id`, `idempotency_key`, `defer_until`.
- Produces response: `{ "lead": OperatorLead, "progression": CustomerProgressionResult }`.

- [ ] **Step 1: Write failing API tests**

```python
def test_operator_promote_returns_consequences(operator_client, seeded_lead):
    response = operator_client.post(
        f"/operator/api/leads/{seeded_lead}/review",
        headers={"Authorization": "Bearer operator-secret"},
        json={"action": "promote", "reason": "需求明确", "idempotency_key": "ui-review-1"},
    )
    assert response.status_code == 200
    assert response.json()["progression"]["customer_stage"] == "awaiting_first_contact"
    assert response.json()["progression"]["next_action"] == "prepare_public_reply"
```

- [ ] **Step 2: Run API tests and verify failure**

Run: `pytest tests/test_operator_api.py -q`  
Expected: FAIL because the response has no `progression` object.

- [ ] **Step 3: Update payload validation and route**

Map legacy values at the API boundary:

```python
LEGACY_ACTIONS = {
    "valid": "promote",
    "follow_up": "promote",
    "watch": "defer",
    "needs_information": "defer",
    "invalid": "reject",
}
```

Generate a server event key only for legacy clients that omit `idempotency_key`; new Miaoda requests must always send one.

- [ ] **Step 4: Run API and service tests**

Run: `pytest tests/test_operator_api.py tests/test_customer_progression.py tests/test_operator_leads.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/routes/operator_api.py tests/test_operator_api.py
git commit -m "feat: expose customer progression results"
```

### Task 4: Make Feishu Valid Review Use the Same Command

**Files:**
- Modify: `apps/api/routes/feishu_callbacks.py`
- Modify: `tests/test_feishu_callbacks.py`

**Interfaces:**
- Consumes: `promote_screening_customer()`.
- Produces timeline event key: `feishu-review:{event_id}`.
- Preserves: existing card update and outreach/comment-reply background behavior.

- [ ] **Step 1: Write failing callback test**

```python
def test_valid_feishu_review_promotes_same_customer(monkeypatch, client):
    promoted = []
    monkeypatch.setattr(
        "apps.api.routes.feishu_callbacks.promote_screening_customer",
        lambda session, screening_id, **kwargs: promoted.append((screening_id, kwargs)),
    )
    response = client.post("/feishu/callback/llm-review", content=_valid_review_payload())
    assert response.status_code == 200
    assert promoted[0][1]["idempotency_key"].startswith("feishu-review:")
```

- [ ] **Step 2: Run callback tests and verify failure**

Run: `pytest tests/test_feishu_callbacks.py -q`  
Expected: FAIL because the unified command is not called.

- [ ] **Step 3: Invoke progression in the callback transaction**

After `apply_llm_review_callback()` returns an applied valid review, call `promote_screening_customer()` before commit. Keep card delivery and draft-generation side effects in background tasks.

- [ ] **Step 4: Run callback and outreach tests**

Run: `pytest tests/test_feishu_callbacks.py tests/test_feishu_outreach.py tests/test_feishu_comment_replies.py -q`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/routes/feishu_callbacks.py tests/test_feishu_callbacks.py
git commit -m "feat: unify Feishu customer promotion"
```

### Task 5: Update Miaoda Review Interaction

**Files:**
- Modify: `miaoda-console/client/src/types/operator.ts`
- Modify: `miaoda-console/client/src/api/operator.ts`
- Modify: `miaoda-console/client/src/pages/LeadReviewPage.tsx`
- Modify: `miaoda-console/client/src/components/operator/LeadReviewQueue.tsx`
- Modify: `miaoda-console/client/src/features/operator/operator-view-model.ts`
- Modify: `miaoda-console/client/src/**/*.test.ts*` matching the changed review flow

**Interfaces:**
- Consumes: Operator API `{lead, progression}` response.
- Produces UI actions: `promote`, `defer`, `reject`.
- Produces completion copy with customer ID, CRM stage, next action, and timeline confirmation.

- [ ] **Step 1: Write failing UI tests**

```tsx
expect(screen.getByRole('button', { name: '推进为客户' })).toBeInTheDocument();
expect(screen.queryByRole('button', { name: '有效' })).not.toBeInTheDocument();
expect(screen.queryByRole('button', { name: '进入跟进' })).not.toBeInTheDocument();
```

Add a response test asserting the success panel renders:

```text
已推进为客户 #151
当前阶段：待首次联系
下一步：准备公开回复
```

- [ ] **Step 2: Run Jest and verify failure**

Run: `cd miaoda-console && npm test -- --runInBand`  
Expected: FAIL because old actions remain.

- [ ] **Step 3: Update types, request payload, labels, and success feedback**

Generate one stable `idempotency_key` per user click and reuse it while the request is pending or retried. Disable the action bar during submission and automatically advance only after the consequence panel is available.

- [ ] **Step 4: Run client verification**

Run: `cd miaoda-console && npm test -- --runInBand && npm run typecheck && npm run lint`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add miaoda-console/client/src
git commit -m "feat: show customer progression in Miaoda"
```

### Task 6: Verify and Record V19-01

**Files:**
- Create: `docs/reports/V19_01_CUSTOMER_PROGRESSION_VERIFICATION.md`
- Modify: `TASKS.md`
- Modify: `PROJECT_DASHBOARD.md`
- Modify: `HANDOFF.md`
- Modify: `DECISIONS.md` only if implementation changes an approved design rule.

**Interfaces:**
- Consumes: all V19-01 code and tests.
- Produces: reproducible automated and real PostgreSQL verification evidence.

- [ ] **Step 1: Run focused backend tests**

Run: `pytest tests/test_customer_timeline_models.py tests/test_customer_progression.py tests/test_operator_leads.py tests/test_operator_api.py tests/test_feishu_callbacks.py -q`  
Expected: PASS.

- [ ] **Step 2: Run full backend regression**

Run: `pytest -q`  
Expected: all non-environmental tests pass; existing documented skips remain skips.

- [ ] **Step 3: Run full Miaoda verification**

Run: `cd miaoda-console && npm test -- --runInBand && npm run typecheck && npm run lint && npm run build`  
Expected: PASS.

- [ ] **Step 4: Run migration and diff checks**

Run: `alembic upgrade head && git diff --check` against the configured PostgreSQL development database.  
Expected: migration `0017` applies and diff check is clean.

- [ ] **Step 5: Perform reversible real PostgreSQL verification**

Select one pending real lead, snapshot every field touched on Lead, latest Screening, and timeline events; call the real Operator API with `action=promote`; verify one timeline event and structured consequences; then restore the snapshot and delete only the verification event. Do not trigger Base sync, public reply generation, or external sending in V19-01 verification.

- [ ] **Step 6: Write the verification report and update project records**

Record exact commands, counts, IDs, restoration proof, remaining V19 tasks, and the fact that V19-01 does not yet implement Base CRM or real sending.

- [ ] **Step 7: Commit**

```bash
git add docs/reports/V19_01_CUSTOMER_PROGRESSION_VERIFICATION.md TASKS.md PROJECT_DASHBOARD.md HANDOFF.md DECISIONS.md
git commit -m "docs: verify V19 customer progression"
```

