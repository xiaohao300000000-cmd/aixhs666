# V19-05 Public Reply Two-Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing Xiaohongshu comment-reply aggregate into a Miaoda-first, versioned two-step approval and send workflow whose real result is reflected in PostgreSQL, Base CRM, Feishu, and the customer timeline without duplicate sends.

**Architecture:** Reuse `LeadCommentReply` and the existing remote-CDP sender instead of creating a second outreach subsystem. Add persistent draft/approval revisions and command-operation idempotency, separate approval from queueing, keep the platform result commit ahead of secondary synchronization, and expose only the normalized operator contract through the NestJS BFF and Miaoda customer page.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, PostgreSQL, persistent Worker tasks, Playwright remote CDP, Feishu/Base integrations, NestJS, React, TypeScript, Jest, pytest.

---

## File map and interface contract

- `storage/models.py`, `alembic/versions/0021_contact_reply_two_step.py`: add `draft_revision`, `approved_revision`, `queued_at` and a persistent `ContactCommandOperation` request/result fact.
- `services/contact_commands.py`: own edit, approve, queue, result-recording and result-unknown recovery invariants.
- `apps/worker/comment_reply_prepare.py`, `services/customer_progression.py`: persist one draft-preparation task after an eligible customer promotion; only the Worker may call the existing generator and Feishu card client.
- `integrations/feishu/comment_replies.py`: turn Feishu into the same two-step command client; no callback may call the platform sender directly.
- `apps/worker/comment_reply_send.py`: claim only the exact approved revision, persist platform result once, then synchronize customer/Base/Feishu facts without re-entering the sender.
- `services/operator_customers.py`, `apps/api/routes/operator_api.py`: expose the current attempt and versioned commands.
- `miaoda-console/server/modules/operator/*`: server-side token-hiding proxy only.
- `miaoda-console/client/src/pages/CustomerDetailPage.tsx`: show draft, approval, final-send confirmation, queued/result state and safe recovery.
- `tests/**`, `miaoda-console/test/unit/**`: lock every state transition, duplicate click and partial-failure behavior before implementation.

Normalized Operator response:

```json
{
  "attempt_id": 41,
  "customer_id": 147,
  "channel": "xiaohongshu_public_reply",
  "target": {"comment_id": "platform-comment-id", "url": "https://www.xiaohongshu.com/explore/..."},
  "draft_text": "公开回复正文",
  "draft_revision": 2,
  "approved_revision": 2,
  "status": "approved",
  "safe_to_send": true,
  "safe_to_retry": false,
  "next_action": "send_approved_contact"
}
```

Only these public states may be returned: `awaiting_approval`, `approved`, `queued`, `sending`, `sent`, `failed`, `result_unknown`, `cancelled`. Legacy `pending_review` maps to `awaiting_approval` and `approved_to_send` maps to `queued`; raw internal task status stays in technical details.

## Task 1: Persist revisions and idempotency

**Files:** `storage/models.py`, `alembic/versions/0021_contact_reply_two_step.py`, `tests/test_contact_commands.py`, `tests/test_lead_comment_reply_migration.py`.

- [ ] Write failing tests proving a reply starts at revision 1, approval can point to an exact revision, and `(operation_scope, entity_id, idempotency_key_hash)` is unique.
- [ ] Run `pytest tests/test_contact_commands.py tests/test_lead_comment_reply_migration.py -q` and capture the expected RED failure caused by missing columns/table.
- [ ] Add the smallest migration and typed SQLAlchemy model fields; do not rewrite migration `0015` or any accepted migration.
- [ ] Upgrade a disposable database, downgrade one revision, upgrade again, and prove existing `lead_comment_replies` rows retain status/text/targets while new revision defaults are valid.
- [ ] Run the focused tests GREEN and commit `feat: persist contact approval revisions`.

Required uniqueness shape:

```python
UniqueConstraint(
    "operation_scope",
    "entity_id",
    "idempotency_key_hash",
    name="uq_contact_command_operations_scope_entity_key",
)
```

## Task 2: Implement versioned commands

**Files:** `services/contact_commands.py`, `tests/test_contact_commands.py`.

- [ ] Write RED tests for edit, approve, queue, duplicate queue, stale revision, illegal transition, sent terminality and `result_unknown` recovery.
- [ ] Implement `edit_contact_draft`, `approve_contact_draft`, `send_approved_contact`, `record_contact_result` and `confirm_contact_not_sent` as typed services.
- [ ] Require a nonblank idempotency key on every write, store only its SHA-256, persist the normalized request and first result, and replay only an identical request.
- [ ] On edit, increment `draft_revision`, set state back to `awaiting_approval`, and leave the prior approval event in the timeline but make it unsendable.
- [ ] On approve, freeze channel, target, exact text, revision, operator and time; create an idempotent `contact_draft_approved` timeline event without sending or creating a send task.
- [ ] On send, require `confirmed=true`, `approved_revision == draft_revision`, exact target/channel, and create one `comment_reply_send` task before returning `queued`.
- [ ] On result, fence by `attempt_count` and revision; `sent` updates the customer to “已联系待回复”, records target/time/account/evidence and one follow-up/timeline fact; `result_unknown` creates a manual verification next action and never queues a retry.
- [ ] Run `pytest tests/test_contact_commands.py -q` GREEN and commit `feat: add versioned contact commands`.

The send precondition must be equivalent to:

```python
safe_to_send = (
    reply.status == "approved"
    and reply.approved_revision == reply.draft_revision
    and reply.approved_text == reply.draft_text
    and confirmed is True
)
```

## Task 3: Prepare the first draft without external calls in the review transaction

**Files:** `services/contact_commands.py`, `services/customer_progression.py`, `apps/worker/comment_reply_prepare.py`, `apps/worker/main.py`, `tests/test_contact_commands.py`, `tests/test_customer_progression.py`, `tests/test_worker_runtime.py`.

- [ ] Write RED tests proving an eligible promoted comment customer creates exactly one `comment_reply_prepare` task, repeated promotion/prepare requests do not duplicate it, and the review transaction never constructs an LLM, Feishu client or browser sender.
- [ ] Implement `prepare_contact_draft` as a persisted command that validates the customer and eligible accepted/valid comment Screening, then creates or replays one preparation task.
- [ ] Add a dedicated Worker handler that calls `OpenAICompatibleCommentReplyGenerator` and `create_comment_reply_for_valid_screening`; a generation or Feishu-card error must remain visible and retryable without creating a second reply.
- [ ] Make newly promoted eligible customers call the same persisted prepare command inside the existing transaction; customers without a valid comment target return an explicit `target_unavailable` outcome rather than a fake draft.
- [ ] Run the focused progression/Worker tests GREEN and commit `feat: queue first public reply drafts`.

The preparation boundary must remain:

```text
review transaction -> persistent comment_reply_prepare task -> Worker -> LLM draft -> PostgreSQL reply -> Feishu card
```

No API request or review transaction may directly call the LLM, Feishu or Xiaohongshu.

## Task 4: Adapt Feishu and Worker without duplicate sends

**Files:** `integrations/feishu/comment_replies.py`, `apps/api/routes/feishu_callbacks.py`, `apps/worker/comment_reply_send.py`, `services/feishu_customer_followup.py`, `services/customer_crm_sync.py`, `tests/test_comment_reply_workflow.py`, `tests/test_feishu_transport_callbacks.py`, `tests/test_worker_runtime.py`, `tests/test_comment_reply_followup_integration.py`, `tests/test_customer_crm_sync.py`.

- [ ] Write RED tests proving the first Feishu action only approves, a second explicit action queues, duplicate callbacks return the first result, and no callback process constructs a sender.
- [ ] Change the card to show “确认话术” first and, after approval, an exact target/channel/text summary with “发送公开回复”; editing the form invalidates the previous approval.
- [ ] Route Feishu callbacks through the same command service and persisted idempotency facts as Miaoda.
- [ ] Keep the Worker as the only real sender. It must claim `queued`, set `sending`, call the remote-CDP sender at most once, record the platform result, and only then run Feishu/Base/customer synchronization.
- [ ] Prove a Feishu/Base synchronization exception leaves the platform outcome persisted and a repair retry never invokes `reply_to_comment`.
- [ ] Prove `result_unknown` has no normal retry action; only an operator-plus-reason confirmation of “平台已核对未发送” can move it to a retryable failed state.
- [ ] Run the focused Feishu/Worker suite GREEN and commit `feat: separate contact approval from sending`.

## Task 5: Expose the Operator contract

**Files:** `services/operator_customers.py`, `apps/api/routes/operator_api.py`, `apps/operator_gateway.py`, `tests/test_customer_crm_operator.py`, `tests/test_operator_api.py`, `tests/test_operator_gateway.py`.

- [ ] Add RED API tests for current attempt read, draft edit, approval, send, duplicate send, stale revision and result-unknown recovery.
- [ ] Add these authenticated routes:

```text
GET  /operator/api/customers/{customer_id}/contact-attempt
POST /operator/api/customers/{customer_id}/contact-attempt/prepare
PUT  /operator/api/customers/{customer_id}/contact-attempt/{attempt_id}/draft
POST /operator/api/customers/{customer_id}/contact-attempt/{attempt_id}/approve
POST /operator/api/customers/{customer_id}/contact-attempt/{attempt_id}/send
POST /operator/api/customers/{customer_id}/contact-attempt/{attempt_id}/confirm-not-sent
```

- [ ] Validate customer/attempt ownership, revision and nonblank idempotency keys; return 404 for wrong ownership, 409 for stale revision/illegal state, 422 for malformed fields and safe 503 for unavailable dependencies.
- [ ] Never expose platform cookies, CDP URL, token, full stack, raw `platform_response_json` or unsanitized integration errors.
- [ ] Run the Operator tests GREEN and commit `feat: expose contact operator commands`.

## Task 6: Build the Miaoda two-step experience

**Files:** `miaoda-console/server/modules/operator/operator.controller.ts`, `miaoda-console/server/modules/operator/operator.service.ts`, `miaoda-console/client/src/api/operator.ts`, `miaoda-console/client/src/types/operator.ts`, `miaoda-console/client/src/features/operator/operator-view-model.ts`, `miaoda-console/client/src/pages/CustomerDetailPage.tsx`, `miaoda-console/test/unit/operator.service.spec.ts`, `miaoda-console/test/unit/operator-view-model.spec.ts`.

- [ ] Add RED BFF tests proving each route forwards the caller idempotency key while the token stays server-side and 409/422/503 remain distinguishable.
- [ ] Add RED pure-view tests for every public state, edited-after-approved invalidation, disabled duplicate clicks, partial synchronization failure and result-unknown recovery.
- [ ] Implement the BFF as a proxy only; do not reproduce the Python state machine in TypeScript.
- [ ] Replace the V19-04 placeholder in customer detail with a real public-reply card: editable draft, revision, target, channel, confirmation identity/time, exact consequence text and refreshable status.
- [ ] If no attempt exists, show the real target-readiness reason and a “生成公开回复草稿” action that only queues preparation, then poll until the Worker returns the draft or a visible failure; never invent a local draft.
- [ ] Step one says “确认话术（不会发送）”. Step two repeats channel, public target and final text, requires an explicit checkbox, and says “发送公开回复”.
- [ ] Keep the same idempotency key while one mutation is pending or being retried; generate a new key only after a new user intent or edited revision.
- [ ] For `result_unknown`, show platform-check instructions and “已核对未发送” with required reason; never show an ordinary retry button.
- [ ] Show Xiaohongshu direct message as “尚未接入”, never as an available channel.
- [ ] Run Jest, typecheck, lint and build GREEN; commit `feat: add Miaoda public reply confirmation`.

## Task 7: Verify the complete result and stop at the real-send gate

**Files:** `docs/reports/V19_05_PUBLIC_REPLY_VERIFICATION.md`, `orchestration/reports/V19-05.md`.

- [ ] Run all focused backend tests, full pytest, Alembic upgrade, Miaoda Jest/type/lint/build and `git diff --check`.
- [ ] Apply migration `0021_contact_reply_two_step` to the real PostgreSQL only after a pre-migration snapshot; prove existing replies are retained and read the new Operator contract without changing business status.
- [ ] Perform a read-only selector probe only when an already authorized target and remote Windows CDP are available; the probe must not fill text, click submit or create external facts.
- [ ] Do not generate a real Feishu card, modify Base, queue a send task or publish to Xiaohongshu during worker acceptance unless the main controller supplies explicit live-acceptance authorization.
- [ ] Record the exact candidate target, final proposed text, account/browser readiness and all preconditions needed for the user’s one-item approval. If any is absent, state `READY_FOR_USER_APPROVAL` or the exact blocker rather than claiming a real send.
- [ ] Produce at least nine meaningful commits in total, with the final commit `docs: verify V19-05 public reply workflow`, then stop for controller acceptance.

## Self-review checklist

- [ ] Every edit after approval makes the old approval unsendable while preserving its timeline audit.
- [ ] Approval never sends; send never bypasses approval; duplicate clicks never create a second task.
- [ ] Platform result is persisted before Base/Feishu synchronization, and synchronization recovery cannot resend.
- [ ] `result_unknown` is never automatically retried.
- [ ] Miaoda, Feishu and PostgreSQL show the same normalized state.
- [ ] No code, test or report claims private message support or a real public reply without live evidence.
- [ ] V19-06 scheduling and reply checking are untouched.
