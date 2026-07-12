# 飞书审批后真实回复小红书评论 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为有效的小红书评论线索生成可编辑的飞书审批卡片，人工确认后立即回复目标评论，并把结果同步到卡片和飞书多维表格客户跟进工作台。

**Architecture:** PostgreSQL 中新增独立的 `LeadCommentReply` 作为发送事实和幂等状态源；飞书卡片回调通过短事务原子领取发送权，事务外调用 Playwright 评论发送器，再用新事务写入明确成功、明确失败或结果不确定。飞书多维表格是运营工作台，只允许人工字段回写本地，评论发送事实始终由数据库覆盖。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、FastAPI、Playwright、Pydantic、飞书 OpenAPI/lark-cli、pytest。

## Global Constraints

- 首版只支持回复 `LeadScreeningResult.source_entity_type == "comment"` 对应的目标评论，不发布帖子一级评论。
- 每次真实评论必须由人工在飞书卡片明确确认；不提供批量确认或无审批自动发送。
- 文案先提供有效帮助，仅在上下文合适时柔和引导私信；禁止索取微信/电话、夸大效果和强营销表达。
- 每个目标评论最多一条成功回复；`sending`、`sent`、`result_unknown` 均不得再次调用平台。
- 明确失败可从同一卡片人工重试；结果不确定必须先人工核对，不能普通重试。
- 本地 PostgreSQL 是评论发送事实源；飞书多维表格是运营工作台，不能覆盖发送结果、发送时间或平台证据。
- 运营可在多维表格维护负责人、备注、下次跟进时间以及 `已收到私信`、`沟通中`、`已成交`、`已忽略` 等人工业务状态。
- 登录失效、验证码、目标缺失或平台限制时停止并记录，不绕过平台权限和风控。
- 核心业务逻辑使用类型标注并有自动测试；数据写入和飞书同步必须幂等。
- 执行每个任务前遵守根目录 `AGENTS.md` 的单任务规则；主控验收后再更新全局进度文件。

---

### Task 1: Persist comment-reply workflow state

**Files:**
- Create: `alembic/versions/0015_lead_comment_replies.py`
- Modify: `storage/models.py:337`
- Modify: `docs/DATA_MODEL.md:318`
- Test: `tests/test_comment_reply_models.py`

**Interfaces:**
- Consumes: existing `LeadScreeningResult`, `Lead`, `Comment`, and `Content` IDs.
- Produces: SQLAlchemy model `LeadCommentReply`, `Lead.followup_status`, `Lead.next_followup_at`, and persisted reply statuses `pending_review`, `sending`, `sent`, `failed`, `result_unknown`.

- [ ] **Step 1: Write the failing model test**

```python
from sqlalchemy.exc import IntegrityError

from storage.models import LeadCommentReply


def test_comment_reply_defaults_and_unique_screening(factory, seeded_comment_screening):
    with factory() as session:
        screening, lead, comment = seeded_comment_screening(session)
        reply = LeadCommentReply(
            screening_result_id=screening.id,
            lead_id=lead.id,
            target_comment_id=comment.id,
            target_platform_comment_id=comment.platform_comment_id,
            target_content_id=comment.content_id,
            target_platform_content_id=comment.content.platform_content_id,
            target_url=comment.content.url,
            draft_text="可以先看看孩子目前卡在哪个题型。",
        )
        session.add(reply)
        session.commit()
        assert reply.status == "pending_review"
        assert reply.attempt_count == 0
        assert lead.followup_status is None
        assert lead.next_followup_at is None

        session.add(
            LeadCommentReply(
                screening_result_id=screening.id,
                target_comment_id=comment.id,
                target_platform_comment_id=comment.platform_comment_id,
                target_content_id=comment.content_id,
                target_platform_content_id=comment.content.platform_content_id,
                draft_text="重复草稿",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
```

- [ ] **Step 2: Run the model test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_comment_reply_models.py -q`

Expected: FAIL because `LeadCommentReply` does not exist.

- [ ] **Step 3: Add the model and migration**

Add this model shape to `storage/models.py`:

```python
class LeadCommentReply(TimestampMixin, Base):
    __tablename__ = "lead_comment_replies"
    __table_args__ = (
        UniqueConstraint("screening_result_id", name="uq_lead_comment_replies_screening_result_id"),
        UniqueConstraint("target_platform_comment_id", name="uq_lead_comment_replies_target_platform_comment_id"),
        Index("ix_lead_comment_replies_target_status", "target_comment_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    screening_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("lead_screening_results.id", ondelete="SET NULL")
    )
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    target_comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    target_platform_comment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_content_id: Mapped[int] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), nullable=False)
    target_platform_content_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_url: Mapped[str | None] = mapped_column(Text)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    approved_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending_review", server_default="pending_review")
    model_name: Mapped[str | None] = mapped_column(String(255))
    feishu_chat_id: Mapped[str | None] = mapped_column(String(255))
    feishu_message_id: Mapped[str | None] = mapped_column(String(255))
    feishu_card_status: Mapped[str | None] = mapped_column(String(50))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_reply_id: Mapped[str | None] = mapped_column(String(255))
    platform_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_error: Mapped[str | None] = mapped_column(Text)
    feishu_sync_error: Mapped[str | None] = mapped_column(Text)
```

Add these dedicated human-workflow fields to `Lead` rather than overloading the existing automated acquisition `status`:

```python
followup_status: Mapped[str | None] = mapped_column(String(50))
next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Create Alembic revision `0015` with the same reply columns, foreign keys, unique constraints and index, plus the two nullable `leads` columns. For XHS-only v1, `target_platform_comment_id` is the durable workflow identity: creation catches `IntegrityError` and loads the existing row by that field. Extend `docs/DATA_MODEL.md` with the ownership and status rules.

- [ ] **Step 4: Run model and migration tests**

Run: `.venv/bin/python -m pytest tests/test_comment_reply_models.py tests/test_core_data_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the schema task**

```bash
git add storage/models.py alembic/versions/0015_lead_comment_replies.py docs/DATA_MODEL.md tests/test_comment_reply_models.py
git commit -m "feat: add comment reply workflow model"
```

### Task 2: Generate and validate helpful reply drafts

**Files:**
- Create: `services/comment_reply_generation.py`
- Test: `tests/test_comment_reply_generation.py`
- Modify: `.env.example:29`

**Interfaces:**
- Consumes: `LeadScreeningResult` plus its `context_json`.
- Produces: `CommentReplyDraft(text: str, model_name: str | None)`, `CommentReplyGenerator.generate(screening)`, and `validate_comment_reply_text(text) -> str`.

- [ ] **Step 1: Write failing generation and validation tests**

```python
def test_generator_requests_helpful_optional_soft_dm_prompt(fake_urlopen, screening):
    generator = OpenAICompatibleCommentReplyGenerator(api_key="key", model="model")
    draft = generator.generate(screening)
    body = fake_urlopen.last_json
    system = body["messages"][0]["content"]
    assert "先提供" in system
    assert "私信" in system
    assert draft.text == "可以先根据错题判断薄弱点，如果方便可以私信聊聊具体情况。"


@pytest.mark.parametrize("text", ["", "加微信详聊", "留下手机号", "保证提分"])
def test_validate_comment_reply_rejects_unsafe_text(text):
    with pytest.raises(ValueError):
        validate_comment_reply_text(text)
```

- [ ] **Step 2: Run generation tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_comment_reply_generation.py -q`

Expected: FAIL because the module and interfaces do not exist.

- [ ] **Step 3: Implement generator and final-text validation**

Create the focused module with these public interfaces:

```python
@dataclass(frozen=True, slots=True)
class CommentReplyDraft:
    text: str
    model_name: str | None = None


class CommentReplyGenerator(Protocol):
    def generate(self, screening: LeadScreeningResult) -> CommentReplyDraft: ...


def validate_comment_reply_text(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        raise ValueError("comment reply text is empty")
    if len(normalized) > 300:
        raise ValueError("comment reply text exceeds 300 characters")
    blocked = ("加微信", "微信号", "手机号", "留下电话", "保证提分", "包过", "百分百")
    if any(term in normalized for term in blocked):
        raise ValueError("comment reply text contains blocked marketing or privacy language")
    return normalized
```

Implement the OpenAI-compatible request by following `services/outreach_generation.py`, but use environment variables `COMMENT_REPLY_GENERATION_API_KEY`, `COMMENT_REPLY_GENERATION_MODEL`, and `COMMENT_REPLY_GENERATION_API_URL`, with existing screening/DeepSeek variables as fallbacks. The system prompt must require a useful public answer first and make the soft private-message invitation optional.

- [ ] **Step 4: Run generation tests**

Run: `.venv/bin/python -m pytest tests/test_comment_reply_generation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit draft generation**

```bash
git add services/comment_reply_generation.py tests/test_comment_reply_generation.py .env.example
git commit -m "feat: generate safe comment reply drafts"
```

### Task 3: Create cards and implement the guarded state machine

**Files:**
- Create: `integrations/feishu/comment_replies.py`
- Test: `tests/test_comment_reply_workflow.py`

**Interfaces:**
- Consumes: `LeadCommentReply`, `CommentReplyGenerator`, a Feishu card client, and `CommentReplySender` from Task 4 through dependency injection.
- Produces: `create_comment_reply_for_valid_screening`, `build_comment_reply_approval_card`, `is_comment_reply_callback`, `apply_comment_reply_callback`, and result dataclasses.

- [ ] **Step 1: Write failing workflow tests for creation and approval**

```python
def test_valid_comment_screening_creates_one_card(factory, seeded_comment_screening):
    with factory() as session:
        screening, _, _ = seeded_comment_screening(session)
        first = create_comment_reply_for_valid_screening(
            session,
            screening_id=screening.id,
            generator=FakeCommentReplyGenerator(),
            card_client=FakeCardClient(),
            chat_id="oc_review",
        )
        second = create_comment_reply_for_valid_screening(
            session,
            screening_id=screening.id,
            generator=FakeCommentReplyGenerator(),
            card_client=FakeCardClient(),
            chat_id="oc_review",
        )
        session.commit()
    assert first.id == second.id
    assert first.status == "pending_review"


def test_callback_sends_once_and_marks_sent(factory, pending_comment_reply):
    sender = FakeCommentReplySender.success(reply_id="reply-1")
    result = apply_comment_reply_callback(
        factory,
        comment_reply_payload(pending_comment_reply.id, "最终回复"),
        card_client=FakeCardClient(),
        sender=sender,
        verification_token="token",
    )
    duplicate = apply_comment_reply_callback(
        factory,
        comment_reply_payload(pending_comment_reply.id, "最终回复"),
        card_client=FakeCardClient(),
        sender=sender,
        verification_token="token",
    )
    assert result.status == "sent"
    assert duplicate.duplicate is True
    assert len(sender.calls) == 1
```

Also add tests for explicit failure retry, `result_unknown`, wrong source type, invalid text, card-update failure, and a conditional-update race where only one callback transitions to `sending`.

- [ ] **Step 2: Run workflow tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_comment_reply_workflow.py -q`

Expected: FAIL because `integrations.feishu.comment_replies` does not exist.

- [ ] **Step 3: Implement creation, card rendering, and three-phase sending**

Use these exact public signatures:

```python
def create_comment_reply_for_valid_screening(
    session: Session,
    *,
    screening_id: int,
    generator: CommentReplyGenerator,
    card_client: FeishuMessageClient,
    chat_id: str,
) -> LeadCommentReply | None: ...


def apply_comment_reply_callback(
    session_factory: sessionmaker[Session],
    payload: dict[str, Any],
    *,
    card_client: FeishuMessageClient,
    sender: CommentReplySender,
    verification_token: str | None,
) -> CommentReplyCallbackResult: ...
```

Implement `_claim_send` as a short conditional update:

```python
statement = (
    update(LeadCommentReply)
    .where(
        LeadCommentReply.id == reply_id,
        LeadCommentReply.status.in_(allowed_from_statuses),
    )
    .values(
        status="sending",
        approved_text=final_text,
        approved_by=operator_id,
        approved_at=now,
        last_attempt_at=now,
        attempt_count=LeadCommentReply.attempt_count + 1,
        last_error=None,
    )
)
claimed = session.execute(statement).rowcount == 1
```

Commit the claim before calling `sender.reply_to_comment`. Classify `CommentReplySendResult.outcome` as `sent`, `failed`, or `result_unknown`; persist the result before attempting Feishu card updates. A retry action is accepted only from `failed`; normal confirmation is accepted only from `pending_review`.

- [ ] **Step 4: Run workflow tests**

Run: `.venv/bin/python -m pytest tests/test_comment_reply_workflow.py tests/test_outreach_workflow.py -q`

Expected: PASS, including regression coverage for the existing private-message workflow.

- [ ] **Step 5: Commit the approval workflow**

```bash
git add integrations/feishu/comment_replies.py tests/test_comment_reply_workflow.py
git commit -m "feat: add approved comment reply workflow"
```

### Task 4: Implement the Playwright target-comment sender

**Files:**
- Create: `collectors/xiaohongshu/comment_reply.py`
- Modify: `collectors/xiaohongshu/__init__.py:1`
- Modify: `collectors/xiaohongshu/selectors.py:1`
- Modify: `collectors/xiaohongshu/exceptions.py:1`
- Test: `tests/test_xhs_comment_reply.py`
- Test: `tests/fixtures/xhs/comment_reply_page.html`

**Interfaces:**
- Consumes: persistent browser settings already used by `XiaohongshuDirectMessageSender`.
- Produces: `CommentReplySendResult`, `CommentReplySender` protocol, and `XiaohongshuCommentReplySender.reply_to_comment(...)`.

- [ ] **Step 1: Write failing sender tests against a deterministic page fixture**

```python
def test_sender_replies_to_exact_comment(fake_browser_page):
    sender = XiaohongshuCommentReplySender(browser_factory=fake_browser_page.factory)
    result = sender.reply_to_comment(
        content_id="note-1",
        comment_id="comment-2",
        text="可以先看孩子目前最薄弱的题型。",
        target_url="https://www.xiaohongshu.com/explore/note-1",
    )
    assert result.outcome == "sent"
    assert fake_browser_page.replied_comment_id == "comment-2"
    assert fake_browser_page.submitted_text == "可以先看孩子目前最薄弱的题型。"


def test_sender_returns_unknown_after_submit_timeout(fake_browser_page):
    fake_browser_page.timeout_after_submit = True
    result = sender.reply_to_comment(...)
    assert result.outcome == "result_unknown"
```

Cover login-required, captcha, missing target comment, explicit platform rejection, and success evidence extraction.

- [ ] **Step 2: Run sender tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_xhs_comment_reply.py -q`

Expected: FAIL because the sender module does not exist.

- [ ] **Step 3: Implement the isolated platform adapter**

Define:

```python
@dataclass(frozen=True, slots=True)
class CommentReplySendResult:
    outcome: Literal["sent", "failed", "result_unknown"]
    platform_reply_id: str | None = None
    response: dict[str, Any] | None = None
    error: str | None = None


class CommentReplySender(Protocol):
    def reply_to_comment(
        self,
        *,
        content_id: str,
        comment_id: str,
        text: str,
        target_url: str,
    ) -> CommentReplySendResult: ...
```

Follow the persistent-context setup and environment parsing in `collectors/xiaohongshu/dm.py`. Keep selectors in `selectors.py`. Locate the target using platform comment ID where available, click its reply control, fill once, submit once, then confirm with platform response or visible posted reply. Exceptions before submit become `failed`; timeout or crash after submit becomes `result_unknown`.

- [ ] **Step 4: Run sender and collector regression tests**

Run: `.venv/bin/python -m pytest tests/test_xhs_comment_reply.py tests/test_xhs_comment_collection.py tests/test_xhs_dm.py -q`

Expected: PASS. If the repository names the existing DM test differently, use `rg --files tests | rg 'xhs.*dm|dm.*xhs'` and run that exact file.

- [ ] **Step 5: Commit the platform sender**

```bash
git add collectors/xiaohongshu/comment_reply.py collectors/xiaohongshu/__init__.py collectors/xiaohongshu/selectors.py collectors/xiaohongshu/exceptions.py tests/test_xhs_comment_reply.py tests/fixtures/xhs/comment_reply_page.html
git commit -m "feat: reply to xhs target comments"
```

### Task 5: Sync the Feishu Base customer workbench bidirectionally

**Files:**
- Create: `services/feishu_customer_followup.py`
- Test: `tests/test_feishu_customer_followup.py`
- Modify: `integrations/feishu/bitable.py:1`
- Modify: `storage/settings.py:12`
- Modify: `.env.example:61`

**Interfaces:**
- Consumes: `LeadCommentReply`, `LeadScreeningResult`, `Lead`, existing `FeishuBitableClient`, and `FeishuBitableRecord` mapping rows.
- Produces: `push_customer_followup`, `pull_customer_followup_edits`, `CustomerFollowupSyncResult`, and settings for a dedicated follow-up table.

- [ ] **Step 1: Write failing push/pull authority tests**

```python
def test_push_maps_sent_reply_to_waiting_for_dm(factory, sent_comment_reply, fake_bitable):
    result = push_customer_followup(factory, reply_id=sent_comment_reply.id, client=fake_bitable)
    assert result.status == "synced"
    assert fake_bitable.upserted_fields["当前客户状态"] == "已评论引导，等待客户私信"
    assert fake_bitable.upserted_fields["评论发送结果"] == "评论成功"


def test_pull_accepts_human_fields_but_ignores_send_facts(factory, customer_mapping, fake_bitable):
    fake_bitable.remote_fields = {
        "负责人": "小王",
        "运营备注": "客户已主动私信",
        "下次跟进时间": "2026-07-15 10:00:00",
        "当前客户状态": "已收到私信",
        "评论发送结果": "未发送",
    }
    pull_customer_followup_edits(factory, client=fake_bitable)
    lead = load_lead(factory)
    reply = load_reply(factory)
    assert lead.followup_status == "已收到私信"
    assert lead.owner_name == "小王"
    assert lead.operator_note == "客户已主动私信"
    assert lead.next_followup_at.isoformat().startswith("2026-07-15T10:00:00")
    assert reply.status == "sent"
```

Add tests proving `已收到私信`, `沟通中`, `已成交`, and `已忽略` are not regressed by later automatic comment synchronization.

- [ ] **Step 2: Run follow-up tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_feishu_customer_followup.py -q`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement dedicated Base settings and authority allowlists**

Add settings:

```python
feishu_customer_followup_app_token: str | None = None
feishu_customer_followup_table_id: str | None = None
```

Load them from `FEISHU_CUSTOMER_FOLLOWUP_APP_TOKEN` and `FEISHU_CUSTOMER_FOLLOWUP_TABLE_ID`. In the sync service define immutable field sets:

```python
SYSTEM_FIELDS = {
    "客户唯一键", "评论审批状态", "评论发送结果", "最近评论时间",
    "最近评论错误", "评论回复记录 ID", "审批卡片消息 ID",
}
HUMAN_FIELDS = {"当前客户状态", "负责人", "运营备注", "下次跟进时间"}
TERMINAL_HUMAN_STATUSES = {"已收到私信", "沟通中", "已成交", "已忽略"}
```

Push by stable customer key `xhs:{platform_user_id}` using idempotent upsert. Pull only `HUMAN_FIELDS`; write `当前客户状态` to `Lead.followup_status`, `负责人` to `Lead.owner_name`, `运营备注` to `Lead.operator_note`, and `下次跟进时间` to `Lead.next_followup_at`, without changing `Lead.status` or `LeadCommentReply.status`.

- [ ] **Step 4: Run Base sync regression tests**

Run: `.venv/bin/python -m pytest tests/test_feishu_customer_followup.py tests/test_feishu_bitable_sync.py tests/test_feishu_ai_review_sync.py -q`

Expected: PASS.

- [ ] **Step 5: Commit customer workbench synchronization**

```bash
git add services/feishu_customer_followup.py integrations/feishu/bitable.py storage/settings.py .env.example tests/test_feishu_customer_followup.py
git commit -m "feat: sync customer followup workbench"
```

### Task 6: Wire immediate sending into callbacks and operator commands

**Files:**
- Modify: `apps/api/routes/feishu_callbacks.py:1`
- Modify: `apps/cli.py:72`
- Modify: `integrations/feishu/__init__.py:1`
- Test: `tests/test_feishu_transport_callbacks.py`
- Test: `tests/test_cli_comment_replies.py`

**Interfaces:**
- Consumes: workflow functions from Task 3, sender from Task 4, and follow-up sync from Task 5.
- Produces: callback routing for comment reply actions and CLI commands `comment-reply-generate-once` and `comment-reply-sync-followup` for controlled recovery/operations.

- [ ] **Step 1: Write failing callback routing tests**

```python
def test_comment_reply_callback_is_accepted_and_runs_immediately(client, monkeypatch):
    calls = []
    monkeypatch.setattr(feishu_callbacks, "_apply_comment_reply_callback", lambda payload: calls.append(payload))
    response = client.post("/callbacks/feishu", json=comment_reply_payload(12, "最终文本"))
    assert response.status_code == 200
    assert response.json()["type"] == "comment_reply"
    assert len(calls) == 1
```

Test callback priority so comment actions are not mistaken for private-message outreach actions. Test CLI JSON output for generated reply ID/status and follow-up sync counts.

- [ ] **Step 2: Run callback and CLI tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_feishu_transport_callbacks.py tests/test_cli_comment_replies.py -q`

Expected: FAIL because callback routing and commands do not exist.

- [ ] **Step 3: Wire dependencies without hiding failures**

In `feishu_callbacks.py`, route `is_comment_reply_callback(payload)` before generic review callbacks. The immediate handler must call `apply_comment_reply_callback(SessionLocal, ...)`, constructing `XiaohongshuCommentReplySender` and the configured Feishu client. After the database send result is final, invoke `push_customer_followup`; catch synchronization failures separately so they never alter or repeat platform sending.

Add CLI parsers:

```python
comment_reply = subparsers.add_parser("comment-reply-generate-once")
comment_reply.add_argument("--screening-id", type=int, required=True)
comment_reply.add_argument("--chat-id", default=None)

subparsers.add_parser("comment-reply-sync-followup")
```

The generation command is an operator recovery path and must not send to Xiaohongshu. The sync command only repairs Feishu Base state.

- [ ] **Step 4: Run callback, CLI, and outreach regressions**

Run: `.venv/bin/python -m pytest tests/test_feishu_transport_callbacks.py tests/test_cli_comment_replies.py tests/test_outreach_workflow.py -q`

Expected: PASS.

- [ ] **Step 5: Commit application wiring**

```bash
git add apps/api/routes/feishu_callbacks.py apps/cli.py integrations/feishu/__init__.py tests/test_feishu_transport_callbacks.py tests/test_cli_comment_replies.py
git commit -m "feat: send approved comments from feishu"
```

### Task 7: Configure Base views/dashboard and document operations

**Files:**
- Create: `docs/COMMENT_REPLY_OPERATIONS.md`
- Modify: `README.md:1`
- Modify: `docs/ARCHITECTURE.md:131`
- Modify: `DECISIONS.md:1`
- Modify: `HANDOFF.md:1`
- Modify: `TASKS.md:406`
- Modify: `PROJECT_DASHBOARD.md:1`
- Test: `tests/test_comment_reply_live_contract.py`

**Interfaces:**
- Consumes: all implemented comment-reply and Base synchronization interfaces.
- Produces: reproducible operator runbook, Base field/view/dashboard specification, and an opt-in live contract test.

- [ ] **Step 1: Write a skipped-by-default live contract test**

```python
@pytest.mark.live
@pytest.mark.skipif(not os.getenv("XHS_COMMENT_REPLY_LIVE_TARGET"), reason="live target is not configured")
def test_live_comment_reply_requires_explicit_target_and_approval():
    target = json.loads(os.environ["XHS_COMMENT_REPLY_LIVE_TARGET"])
    assert target["content_id"]
    assert target["comment_id"]
    assert os.environ.get("XHS_COMMENT_REPLY_LIVE_APPROVED") == "yes"
```

Extend the test during implementation to invoke the sender only when both variables are explicitly present; never embed a real target or credential in the repository.

- [ ] **Step 2: Run the live contract test and confirm safe skip**

Run: `.venv/bin/python -m pytest tests/test_comment_reply_live_contract.py -q`

Expected: `1 skipped` without live environment variables.

- [ ] **Step 3: Write the operator runbook and Base setup**

Document exact setup and recovery procedures:

```text
1. Run Alembic upgrade.
2. Configure COMMENT_REPLY_GENERATION_* and FEISHU_CUSTOMER_FOLLOWUP_*.
3. Create/verify Base fields using the names in Task 5.
4. Create views: 评论待审核、评论发送失败、评论结果待确认、等待客户私信、沟通中、今日待跟进、已成交/已忽略.
5. Create a Base dashboard with status counts, conversion funnel, daily trend, owner distribution, and failure reasons.
6. Start the API callback service with the persistent XHS browser profile.
7. Generate one approval card for a prepared test comment.
8. Review/edit and click 确认发送.
9. Verify the target comment, card status, database row, and customer Base row.
10. If result_unknown occurs, inspect the target page before any manual recovery.
```

Record the architectural decision that PostgreSQL owns system facts while Base owns permitted human workflow fields. Update project status documents only after automated and live acceptance results are known.

- [ ] **Step 4: Run full automated verification**

Run: `.venv/bin/python -m pytest -q`

Expected: all non-live tests pass; existing live tests remain skipped unless explicitly configured.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 5: Perform one explicit live acceptance with human approval**

Run only after preparing a dedicated test post/comment and confirming the current account is allowed to reply:

```bash
XHS_COMMENT_REPLY_LIVE_TARGET='{"content_id":"<test-note-id>","comment_id":"<test-comment-id>","target_url":"<test-note-url>","text":"<approved-test-reply>"}' \
XHS_COMMENT_REPLY_LIVE_APPROVED=yes \
.venv/bin/python -m pytest tests/test_comment_reply_live_contract.py -m live -q
```

Expected: one reply appears under the exact target comment, the database row is `sent`, the Feishu card displays `评论成功`, and the Base customer status is `已评论引导，等待客户私信`. If the result is `failed` or `result_unknown`, stop and record evidence; do not retry until the status rules permit it.

- [ ] **Step 6: Commit documentation and accepted status**

```bash
git add docs/COMMENT_REPLY_OPERATIONS.md README.md docs/ARCHITECTURE.md DECISIONS.md HANDOFF.md TASKS.md PROJECT_DASHBOARD.md tests/test_comment_reply_live_contract.py
git commit -m "docs: document approved comment reply operations"
```
