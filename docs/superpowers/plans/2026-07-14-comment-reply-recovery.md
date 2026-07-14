# Comment Reply Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the interrupted comment-reply automation work by aligning the operator runbook with the persistent Worker and remote Windows CDP architecture, verifying the complete test suite, and recording only evidence-backed status.

**Architecture:** Feishu callbacks validate and persist approval as `approved_to_send`, enqueue one `comment_reply_send` task, and return immediately. The Worker conditionally claims the approved reply, connects to the existing Windows Chromium context through CDP, performs one fenced send attempt, and synchronizes Feishu and customer-follow-up state without allowing sync retries to resend on Xiaohongshu.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Playwright sync API, pytest, Markdown operator documentation.

## Global Constraints

- Do not run a live selector probe or live Xiaohongshu comment send in this recovery.
- Do not place target URLs, comment IDs, approved text, cookies, tokens, or credentials in repository files, logs, shell history, or tests.
- Production comment replies use `COMMENT_REPLY_BROWSER_MODE=remote_cdp` and `COMMENT_REPLY_CDP_URL`; remote failure must never fall back to a local Mac browser.
- `result_unknown` requires human verification and must never be retried automatically.
- Feishu/Base synchronization retries must never invoke the Xiaohongshu sender.
- Do not create a Git commit unless the user explicitly requests one.

---

### Task 1: Align the operator runbook

**Files:**
- Modify: `docs/COMMENT_REPLY_OPERATIONS.md`
- Reference: `docs/superpowers/specs/2026-07-14-comment-reply-recovery-design.md`

**Interfaces:**
- Consumes: `enqueue_comment_reply_callback(...)`, `execute_approved_comment_reply(...)`, `run_comment_reply_send_task(...)`, `XiaohongshuBrowserConfig.from_env()`.
- Produces: an operator contract that accurately describes approval enqueueing, Worker sending, remote CDP configuration, status mapping, recovery, and live blockers.

- [ ] **Step 1: Confirm the stale synchronous documentation fails the new contract**

Run:

```bash
rg -n '同步发送状态机|原子领取发送权并同步执行|评论回复发送当前位于同步回调路径' docs/COMMENT_REPLY_OPERATIONS.md
```

Expected: matches at the current-status and callback-operation sections, proving the runbook still describes the removed synchronous path.

- [ ] **Step 2: Replace the current acceptance summary**

Change the opening summary to state:

```markdown
- **自动化实现：完成，待全量验证。** 数据模型、迁移、草稿生成、飞书卡片审批、`approved_to_send` 持久任务、Worker 独立发送、远程 Windows CDP、客户跟进同步、恢复/认领命令和定向自动测试均已实现。
- **真实发送验收：阻塞。** 截至 2026-07-13，Windows CDP/SSH 当前不可用，且未提供专用测试 URL、评论 ID、内容 ID、最终批准文本和客户跟进 Base live 配置，因此不得声称真实发送成功。
- **解除阻塞条件：** 恢复 Windows Chrome CDP；准备一个允许测试的目标帖子/评论和最终回复文本；先运行不提交的 selector probe；人工在飞书明确批准本次单条测试；最后才允许执行一次真实发送。
```

- [ ] **Step 3: Document remote CDP and Worker configuration**

Add these non-secret example variables to the configuration section:

```env
COMMENT_REPLY_BROWSER_MODE=remote_cdp
COMMENT_REPLY_CDP_URL=http://WINDOWS_TAILSCALE_IP:RELAY_PORT
```

State that `remote_cdp` requires Chromium, reuses the first existing browser context, does not close the Windows context, and fails explicitly rather than launching a local Mac browser.

- [ ] **Step 4: Replace the callback operation description**

Document this flow exactly:

```text
人工在飞书确认最终文本
→ 回调校验 token、操作人、消息和 chat 绑定
→ 状态写为 approved_to_send
→ 创建一个 comment_reply_send 持久任务
→ 回调立即返回 accepted
→ Worker 条件领取并写为 sending
→ 通过 Windows Chrome CDP 执行一次发送
→ 持久化 sent / failed / result_unknown
→ 更新飞书结果卡片
→ 独立同步客户跟进表
```

Replace the old callback latency gate with a gate that verifies fast enqueue response, duplicate callback idempotency, one persistent task, and no sender construction in the callback process.

- [ ] **Step 5: Add the approved status mapping and Worker operations**

Update the automatic Base mapping to include:

```text
approved_to_send=评论已批准，等待发送
```

State that normal Worker startup processes `comment_reply_send`; follow-up repair remains `python -m apps.cli comment-reply-sync-followup --reply-id REPLY_ID` and must not send to Xiaohongshu.

- [ ] **Step 6: Verify stale synchronous language is removed**

Run:

```bash
rg -n '同步发送状态机|原子领取发送权并同步执行|评论回复发送当前位于同步回调路径' docs/COMMENT_REPLY_OPERATIONS.md
```

Expected: no matches.

Run:

```bash
rg -n 'approved_to_send|comment_reply_send|remote_cdp|Windows Chrome CDP|立即返回' docs/COMMENT_REPLY_OPERATIONS.md
```

Expected: each architecture term appears in the relevant configuration and operation sections.

### Task 2: Verify focused automation contracts

**Files:**
- Verify: `collectors/xiaohongshu/browser.py`
- Verify: `collectors/xiaohongshu/comment_reply.py`
- Verify: `integrations/feishu/comment_replies.py`
- Verify: `apps/api/routes/feishu_callbacks.py`
- Verify: `apps/worker/comment_reply_send.py`
- Test: `tests/test_xhs_comment_reply.py`
- Test: `tests/test_comment_reply_workflow.py`
- Test: `tests/test_feishu_transport_callbacks.py`
- Test: `tests/test_worker_runtime.py`
- Test: `tests/test_comment_reply_live_contract.py`

**Interfaces:**
- Consumes: the current uncommitted implementation and its existing regression tests.
- Produces: evidence that callback enqueueing, persistent task dispatch, remote CDP reuse, reply-control expansion, and safe live skipping work together.

- [ ] **Step 1: Run the focused suite**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/test_xhs_comment_reply.py \
  tests/test_comment_reply_workflow.py \
  tests/test_feishu_transport_callbacks.py \
  tests/test_worker_runtime.py \
  tests/test_comment_reply_live_contract.py
```

Expected: all non-live tests pass; live tests skip because no live environment is injected. The recovered baseline result is `82 passed, 3 skipped, 1 warning`.

- [ ] **Step 2: Review the focused diff for safety invariants**

Run:

```bash
git diff -- \
  apps/api/routes/feishu_callbacks.py \
  apps/worker/main.py \
  apps/worker/comment_reply_send.py \
  collectors/xiaohongshu/browser.py \
  collectors/xiaohongshu/comment_reply.py \
  integrations/feishu/comment_replies.py \
  services/feishu_customer_followup.py \
  tests/test_comment_reply_live_contract.py \
  tests/test_comment_reply_workflow.py \
  tests/test_feishu_transport_callbacks.py \
  tests/test_worker_runtime.py \
  tests/test_xhs_comment_reply.py
```

Expected review findings:

- The API callback imports and invokes `enqueue_comment_reply_callback`, not a sender.
- Duplicate approval cannot create a second task because the reply status is no longer in the allowed source state.
- The Worker claims only `approved_to_send` and fences completion with `attempt_count`.
- Remote CDP never invokes `launch_persistent_context` and does not close the reused context.
- The sender clicks the unique reply trigger before waiting for editor and submit controls.
- Probe expansion never fills or submits.

- [ ] **Step 3: Fix only evidence-backed defects using TDD**

If a focused test or diff review exposes a defect:

1. Add or adjust one regression test that fails for the exact defect.
2. Run only that test and confirm the expected failure.
3. Apply the smallest implementation change.
4. Run the exact test and the focused suite again.

Do not refactor unrelated task queue, Feishu, or collector code.

### Task 3: Run complete automated verification

**Files:**
- Verify: all tracked Python and test files.

**Interfaces:**
- Consumes: the documentation-aligned, focused-test-passing workspace.
- Produces: repository-wide compatibility evidence.

- [ ] **Step 1: Run the full test suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all non-live tests pass; environment-dependent tests remain explicitly skipped. Record the exact counts and warning summary rather than copying the historical `305 passed, 4 skipped` result.

- [ ] **Step 2: Diagnose any failure before editing**

For each failure:

1. Re-run the single failing node ID with `-vv`.
2. Determine whether it is caused by the comment-reply changes or an unrelated environmental condition.
3. For an in-scope regression, follow the TDD sequence in Task 2 Step 3.
4. For an unrelated existing or environmental failure, do not change unrelated code; record it in the final handoff.

- [ ] **Step 3: Re-run the full suite after any fix**

Run the complete command again and require a fresh passing result before updating project status.

### Task 4: Reconcile documentation and project status

**Files:**
- Modify: `TASKS.md`
- Modify: `PROJECT_DASHBOARD.md`
- Modify: `HANDOFF.md`
- Modify if a new architectural decision is discovered: `DECISIONS.md`

**Interfaces:**
- Consumes: exact focused and full-suite verification results.
- Produces: evidence-backed project state that distinguishes automated completion from live acceptance.

- [ ] **Step 1: Update the Task 7/V06 status with exact evidence**

Record:

- the exact full-suite passed/skipped/warning counts and date;
- that the callback now persists one task and returns `accepted`;
- that Worker and remote CDP paths are covered by automated tests;
- that no live selector probe or send was run;
- that Windows CDP/SSH and live target/Base configuration remain blockers.

Keep Task 7 as `DONE_AUTOMATED / LIVE_BLOCKED` and V06 as `BLOCKED` unless a separate live acceptance is later completed.

- [ ] **Step 2: Avoid unsupported decisions**

Do not add another decision entry if the implementation remains within `D021` and `D022`. Add a new decision only if verification forces a genuine architecture change.

- [ ] **Step 3: Verify status wording does not claim live success**

Run:

```bash
rg -n '真实发送成功|live.*完成|LIVE_DONE|真实验收.*完成' README.md TASKS.md PROJECT_DASHBOARD.md HANDOFF.md docs/COMMENT_REPLY_OPERATIONS.md
```

Expected: no new statement claims live comment-reply success; historical statements about other verified flows must remain contextually accurate.

### Task 5: Final diff and repository checks

**Files:**
- Verify: complete working tree.

**Interfaces:**
- Consumes: all completed recovery changes and verification evidence.
- Produces: a reviewable, uncommitted handoff.

- [ ] **Step 1: Check whitespace and patch integrity**

Run:

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 2: Review changed-file scope**

Run:

```bash
git status --short
git diff --stat
```

Expected: changes remain limited to the recovered comment-reply implementation, its tests, configuration examples, project status documents, and the approved recovery spec/plan.

- [ ] **Step 3: Review the complete diff**

Run:

```bash
git diff -- . ':(exclude)THINKING.md'
```

Confirm there are no credentials, live targets, accidental local paths, silent local-browser fallbacks, duplicate-send paths, or unrelated refactors.

- [ ] **Step 4: Report without committing**

Report exact verification results, modified files, remaining live blockers, and known risks. Leave the working tree uncommitted unless the user explicitly requests a commit.
