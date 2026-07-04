# Agent Feishu Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PostgreSQL-backed agent workflow that prioritizes leads, syncs user-friendly customer rows to one Feishu Bitable table, and reads Feishu status changes back into the system.

**Architecture:** PostgreSQL remains the source of truth. `PipelineRunner` keeps doing collection and analysis, a new agent layer ranks leads and prepares user-facing fields, and a new Feishu Bitable sync layer handles idempotent write/read synchronization. Existing HTML pages stay in the repo as optional debug views.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, httpx, pytest, PostgreSQL, Feishu Open Platform Bitable API.

## Global Constraints

- Do not delete existing `/leads` or `/ops` HTML pages.
- Do not use Feishu Bitable as the system master database.
- First version uses one Feishu table named `客户跟进表`.
- User-visible Feishu fields must use human-readable Chinese labels.
- Do not expose `lead_evidence`, `pipeline_runs`, `needs_enrichment`, or other internal terms in Feishu.
- Agent may select queries, rank leads, and write user-facing explanations.
- Agent must not automatically modify code or rewrite rules.
- No automatic private messages, automatic comments, or automatic sales actions.
- Artificial credentials must not be committed.
- All real Feishu integration must support dry-run when credentials are missing.

---

## File Structure

- Create `services/lead_intent.py`: structured demand-recognition types and rule-based first-pass classifier.
- Modify `services/lead_generation.py`: use `lead_intent` output instead of direct one-step lead classification.
- Create `services/agent_runtime.py`: query selection, lead prioritization, and pipeline orchestration glue.
- Create `integrations/feishu/bitable.py`: Feishu Bitable settings, token client, record write/read helpers, and dry-run support.
- Create `services/feishu_workbench.py`: convert internal leads to the human-readable `客户跟进表` schema and sync records idempotently.
- Modify `storage/models.py`: add `FeishuBitableRecord` mapping and optional human feedback fields on `Lead`.
- Create `alembic/versions/0008_feishu_bitable_sync.py`: database migration for Feishu sync records and feedback fields.
- Modify `apps/cli.py`: add `agent-run`, `feishu-sync`, and `feishu-pull-feedback` commands.
- Modify `.env.example`: document Feishu Bitable settings without secrets.
- Add focused tests in `tests/test_lead_intent.py`, `tests/test_agent_runtime.py`, `tests/test_feishu_bitable_sync.py`, and update existing lead/pipeline tests.

---

### Task 1: Structured Lead Intent Recognition

**Files:**
- Create: `services/lead_intent.py`
- Modify: `services/lead_generation.py`
- Test: `tests/test_lead_intent.py`
- Test: `tests/test_lead_generation.py`

**Interfaces:**
- Produces: `class LeadEntryType(str, Enum)` with values `push`, `confirm`, `skip`
- Produces: `class LeadIntentAction(str, Enum)` with values `course`, `institution`, `price`, `trial`, `enrollment`, `exam_retry`, `comparison`, `improvement`
- Produces: `class LeadSkipReason(str, Enum)` with values `ad`, `provider`, `guide`, `resource_request`, `no_clear_need`, `out_of_scope`, `unknown`
- Produces: `@dataclass(frozen=True, slots=True) class LeadIntentDecision`
- Produces: `classify_lead_intent(text: str, *, source_entity_type: str, context_text: str = "") -> LeadIntentDecision`
- Consumes: Existing `services.lead_generation._classify_lead_event`

- [ ] **Step 1: Write failing tests for hard exclusions**

Add `tests/test_lead_intent.py`:

```python
from services.lead_intent import LeadEntryType, LeadSkipReason, classify_lead_intent


def test_provider_and_guide_content_are_skipped() -> None:
    provider = classify_lead_intent("教了9年PET，总结出来的备考规划，欢迎咨询课程", source_entity_type="content")
    guide = classify_lead_intent("PET备考资料汇总，求资料的姐妹看这里", source_entity_type="content")

    assert provider.entry_type == LeadEntryType.SKIP
    assert provider.skip_reason == LeadSkipReason.PROVIDER
    assert guide.entry_type == LeadEntryType.SKIP
    assert guide.skip_reason in {LeadSkipReason.GUIDE, LeadSkipReason.RESOURCE_REQUEST}


def test_resource_request_is_not_a_customer() -> None:
    decision = classify_lead_intent("求PET真题资料，谢谢", source_entity_type="comment")

    assert decision.entry_type == LeadEntryType.SKIP
    assert decision.skip_reason == LeadSkipReason.RESOURCE_REQUEST
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_lead_intent.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'services.lead_intent'`.

- [ ] **Step 3: Implement `services/lead_intent.py`**

Create the file with:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from intelligence.text_processing import normalize_text


class LeadEntryType(str, Enum):
    PUSH = "push"
    CONFIRM = "confirm"
    SKIP = "skip"


class LeadIntentAction(str, Enum):
    COURSE = "course"
    INSTITUTION = "institution"
    PRICE = "price"
    TRIAL = "trial"
    ENROLLMENT = "enrollment"
    EXAM_RETRY = "exam_retry"
    COMPARISON = "comparison"
    IMPROVEMENT = "improvement"


class LeadSkipReason(str, Enum):
    AD = "ad"
    PROVIDER = "provider"
    GUIDE = "guide"
    RESOURCE_REQUEST = "resource_request"
    NO_CLEAR_NEED = "no_clear_need"
    OUT_OF_SCOPE = "out_of_scope"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LeadIntentDecision:
    entry_type: LeadEntryType
    actions: tuple[LeadIntentAction, ...] = ()
    confidence: str = "low"
    human_need: str = ""
    recommendation_reason: str = ""
    suggested_next_step: str = ""
    missing_info: tuple[str, ...] = ()
    skip_reason: LeadSkipReason | None = None


TARGET_PRODUCTS = ("KET", "PET", "ket", "pet", "小剑桥")
RESOURCE_WORDS = ("求资料", "求分享", "蹲资料", "发我一份", "领取资料", "资料包")
PROVIDER_WORDS = ("招生", "欢迎咨询", "课程顾问", "老师带", "教了", "机构", "私信我", "报名入口")
GUIDE_WORDS = ("攻略", "汇总", "总结", "干货", "备考规划", "避坑指南")
OUT_OF_SCOPE_WORDS = ("雅思", "托福", "PTE", "考研", "成人英语", "四六级")
ACTION_PATTERNS: tuple[tuple[LeadIntentAction, tuple[str, ...]], ...] = (
    (LeadIntentAction.PRICE, ("多少钱", "价格", "费用", "收费", "课时费")),
    (LeadIntentAction.TRIAL, ("试听", "体验课")),
    (LeadIntentAction.ENROLLMENT, ("报班", "报名", "要不要报", "需要报")),
    (LeadIntentAction.INSTITUTION, ("推荐机构", "机构推荐", "哪家机构", "线下机构", "线上机构")),
    (LeadIntentAction.COURSE, ("线上带", "线下课", "冲刺班", "课程", "一对一")),
    (LeadIntentAction.EXAM_RETRY, ("没过", "压线", "二刷", "重考", "再考")),
    (LeadIntentAction.COMPARISON, ("哪个好", "怎么选", "纠结", "对比")),
    (LeadIntentAction.IMPROVEMENT, ("怎么提高", "怎么提升", "阅读弱", "听力弱", "写作弱", "跟不上")),
)


def classify_lead_intent(text: str, *, source_entity_type: str, context_text: str = "") -> LeadIntentDecision:
    raw = " ".join(part for part in (context_text, text) if part)
    normalized = normalize_text(raw)
    if not _contains_any(normalized, TARGET_PRODUCTS):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.OUT_OF_SCOPE)
    if _contains_any(normalized, OUT_OF_SCOPE_WORDS) and not _contains_any(normalized, ("KET", "PET", "ket", "pet")):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.OUT_OF_SCOPE)
    if _contains_any(normalized, RESOURCE_WORDS):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.RESOURCE_REQUEST)
    if source_entity_type == "content" and _contains_any(normalized, PROVIDER_WORDS):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.PROVIDER)
    if source_entity_type == "content" and _contains_any(normalized, GUIDE_WORDS) and not _contains_question(normalized):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.GUIDE)

    actions = _detect_actions(normalized)
    if not actions:
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.NO_CLEAR_NEED)

    confidence = "high" if len(actions) >= 2 or _contains_any(normalized, ("孩子", "娃", "五年级", "四年级", "福州")) else "medium"
    entry_type = LeadEntryType.PUSH if confidence == "high" else LeadEntryType.CONFIRM
    missing = _missing_info(normalized)
    return LeadIntentDecision(
        entry_type=entry_type,
        actions=actions,
        confidence=confidence,
        human_need=_human_need(actions),
        recommendation_reason=_recommendation_reason(actions, confidence),
        suggested_next_step=_next_step(missing, actions),
        missing_info=missing,
    )


def _detect_actions(normalized: str) -> tuple[LeadIntentAction, ...]:
    actions: list[LeadIntentAction] = []
    for action, words in ACTION_PATTERNS:
        if _contains_any(normalized, words):
            actions.append(action)
    return tuple(actions)


def _missing_info(normalized: str) -> tuple[str, ...]:
    missing: list[str] = []
    if not _contains_any(normalized, ("福州", "厦门", "上海", "北京", "线上", "线下")):
        missing.append("地区")
    if not _contains_any(normalized, ("一年级", "二年级", "三年级", "四年级", "五年级", "六年级", "孩子", "娃")):
        missing.append("年级")
    if not _contains_any(normalized, ("考试", "暑假", "寒假", "本月", "下个月", "二刷")):
        missing.append("考试时间")
    return tuple(missing)


def _human_need(actions: tuple[LeadIntentAction, ...]) -> str:
    if LeadIntentAction.EXAM_RETRY in actions:
        return "孩子考试没过或准备二刷，家长在找提升方案"
    if LeadIntentAction.PRICE in actions:
        return "家长在了解课程价格"
    if LeadIntentAction.INSTITUTION in actions:
        return "家长在找合适的英语机构"
    if LeadIntentAction.IMPROVEMENT in actions:
        return "家长在询问孩子英语提升方法"
    return "家长在咨询KET/PET相关学习安排"


def _recommendation_reason(actions: tuple[LeadIntentAction, ...], confidence: str) -> str:
    action_names = "、".join(action.value for action in actions)
    return f"文本包含明确咨询动作：{action_names}；置信度为{confidence}"


def _next_step(missing: tuple[str, ...], actions: tuple[LeadIntentAction, ...]) -> str:
    if missing:
        return f"先确认{missing[0]}，再判断是否适合跟进"
    if LeadIntentAction.PRICE in actions:
        return "可先询问孩子年级和目标考试时间，再给课程建议"
    return "可根据原评论问题做一次轻量人工判断"


def _contains_question(normalized: str) -> bool:
    return "?" in normalized or "？" in normalized or any(word in normalized for word in ("请问", "怎么", "要不要", "有没有"))


def _contains_any(normalized: str, words: tuple[str, ...]) -> bool:
    return any(word in normalized for word in words)
```

- [ ] **Step 4: Add tests for push/confirm decisions**

Append:

```python
from services.lead_intent import LeadIntentAction


def test_high_intent_parent_question_is_pushed() -> None:
    decision = classify_lead_intent("孩子PET没过，福州有二刷冲刺班推荐吗？", source_entity_type="comment")

    assert decision.entry_type == LeadEntryType.PUSH
    assert LeadIntentAction.EXAM_RETRY in decision.actions
    assert LeadIntentAction.INSTITUTION in decision.actions
    assert decision.confidence == "high"
    assert decision.human_need
    assert decision.suggested_next_step


def test_incomplete_parent_question_needs_confirmation() -> None:
    decision = classify_lead_intent("请问PET阅读怎么提高？", source_entity_type="comment")

    assert decision.entry_type == LeadEntryType.CONFIRM
    assert LeadIntentAction.IMPROVEMENT in decision.actions
    assert "地区" in decision.missing_info
```

- [ ] **Step 5: Wire `lead_generation` to `classify_lead_intent`**

Modify `_build_candidate` in `services/lead_generation.py` so each record calls `classify_lead_intent(record.text, source_entity_type=record.source_entity_type, context_text=combined_text)`. Skip only when `decision.entry_type == LeadEntryType.SKIP`. Use `decision.human_need`, `decision.recommendation_reason`, and `decision.suggested_next_step` in `known_info_json` and `recommended_next_step`.

The minimal code change inside the loop should look like:

```python
decision = classify_lead_intent(record.text, source_entity_type=record.source_entity_type, context_text=combined_text)
if decision.entry_type == LeadEntryType.SKIP:
    continue
event_type = _classify_lead_event(record.text, source_entity_type=record.source_entity_type)
if event_type == DemandEventType.UNKNOWN:
    demand_type = decision.actions[0].value if decision.actions else "question"
    intent_stage = "exploring"
else:
    demand_type = event_type.value
    intent_stage = _stage_for_event(event_type).value
evidence.append((record, _score_record(record.text, event_type), demand_type, intent_stage))
```

- [ ] **Step 6: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_lead_intent.py tests/test_lead_generation.py -q`

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/lead_intent.py services/lead_generation.py tests/test_lead_intent.py tests/test_lead_generation.py
git commit -m "feat: structure lead intent recognition"
```

---

### Task 2: Agent Lead Prioritizer and Runtime

**Files:**
- Create: `services/agent_runtime.py`
- Test: `tests/test_agent_runtime.py`
- Modify: `services/pipeline_runner.py`

**Interfaces:**
- Consumes: `PipelineRunner.run_cycle(...) -> dict[str, Any]`
- Produces: `@dataclass(frozen=True, slots=True) class AgentLeadRow`
- Produces: `select_queries_for_agent(session: Session, *, limit: int = 3) -> list[int]`
- Produces: `rank_leads_for_workbench(session: Session, *, limit: int = 50) -> list[AgentLeadRow]`
- Produces: `run_agent_cycle(session_factory: sessionmaker[Session], runner: PipelineRunner, *, query_limit: int = 3, collection_limit: int = 20) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_agent_runtime.py`:

```python
from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from services.agent_runtime import rank_leads_for_workbench, select_queries_for_agent
from storage.database import Base
from storage.models import Lead, PublicProfile, Query


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield SessionLocal
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_select_queries_prefers_active_high_priority_queries(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add_all([
            Query(query_text="低优先", platform="xhs", query_type="seed", status="active", priority=1),
            Query(query_text="高优先", platform="xhs", query_type="seed", status="active", priority=9),
            Query(query_text="暂停", platform="xhs", query_type="seed", status="paused", priority=99),
        ])
        session.commit()

    with factory() as session:
        ids = select_queries_for_agent(session, limit=1)
        query = session.get(Query, ids[0])
        assert query is not None
        assert query.query_text == "高优先"


def test_rank_leads_outputs_user_facing_rows(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="u1", display_name="福州家长")
        session.add(profile)
        session.flush()
        session.add(Lead(
            platform="xhs",
            public_profile_id=profile.id,
            status="needs_enrichment",
            product="PET",
            demand_type="exam_retry",
            intent_stage="exploring",
            intent_score=82,
            information_completeness=70,
            known_info_json={"human_need": "孩子PET二刷需要冲刺", "recommendation_reason": "明确问二刷冲刺班"},
            missing_info_json=["contact"],
            recommended_next_step="先确认考试时间",
        ))
        session.commit()

    with factory() as session:
        rows = rank_leads_for_workbench(session)

    assert len(rows) == 1
    assert rows[0].customer == "福州家长"
    assert rows[0].status_label == "待确认"
    assert rows[0].need == "孩子PET二刷需要冲刺"
    assert rows[0].next_step == "先确认考试时间"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agent_runtime.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'services.agent_runtime'`.

- [ ] **Step 3: Implement `services/agent_runtime.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from services.pipeline_runner import PipelineRunner
from storage.models import Lead, Query


STATUS_LABELS = {
    "new": "新发现",
    "needs_enrichment": "待确认",
    "qualified": "可跟进",
    "handled": "已跟进",
    "ignored": "不合适",
}


@dataclass(frozen=True, slots=True)
class AgentLeadRow:
    lead_id: int
    customer: str
    need: str
    product: str
    intent_level: str
    reason: str
    next_step: str
    status_label: str
    source_url: str
    discovered_at: str


def select_queries_for_agent(session: Session, *, limit: int = 3) -> list[int]:
    rows = session.scalars(
        select(Query)
        .where(Query.status == "active")
        .order_by(Query.priority.desc(), Query.last_run_at.asc().nullsfirst(), Query.id.asc())
        .limit(limit)
    ).all()
    return [query.id for query in rows if query.id is not None]


def rank_leads_for_workbench(session: Session, *, limit: int = 50) -> list[AgentLeadRow]:
    leads = session.scalars(
        select(Lead)
        .where(Lead.status.in_(("new", "needs_enrichment", "qualified")))
        .order_by(Lead.intent_score.desc(), Lead.last_seen_at.desc(), Lead.id.desc())
        .limit(limit)
    ).all()
    return [_lead_to_row(lead) for lead in leads]


def run_agent_cycle(
    session_factory: sessionmaker[Session],
    runner: PipelineRunner,
    *,
    query_limit: int = 3,
    collection_limit: int = 20,
) -> dict[str, Any]:
    with session_factory() as session:
        query_ids = select_queries_for_agent(session, limit=query_limit)
    result = runner.run_cycle(query_ids=query_ids, collection_limit=collection_limit, requested_by="agent")
    with session_factory() as session:
        rows = rank_leads_for_workbench(session)
    return {"pipeline": result, "workbench_rows": [row.__dict__ for row in rows]}


def _lead_to_row(lead: Lead) -> AgentLeadRow:
    profile = lead.profile
    known = lead.known_info_json or {}
    customer = profile.display_name if profile and profile.display_name else (profile.platform_user_id if profile else f"lead-{lead.id}")
    need = str(known.get("human_need") or _fallback_need(lead))
    reason = str(known.get("recommendation_reason") or "系统根据公开内容判断有跟进价值")
    return AgentLeadRow(
        lead_id=lead.id,
        customer=customer,
        need=need,
        product=lead.product or "未知",
        intent_level=_intent_level(lead.intent_score),
        reason=reason,
        next_step=lead.recommended_next_step or "先人工确认需求是否真实",
        status_label=STATUS_LABELS.get(lead.status, "待确认"),
        source_url=profile.profile_url if profile and profile.profile_url else "",
        discovered_at=lead.first_seen_at.isoformat() if lead.first_seen_at else "",
    )


def _fallback_need(lead: Lead) -> str:
    product = lead.product or "课程"
    if lead.demand_type == "exam_retry":
        return f"家长可能需要{product}二刷或冲刺帮助"
    return f"家长可能在咨询{product}相关问题"


def _intent_level(score: int) -> str:
    if score >= 80:
        return "高"
    if score >= 60:
        return "中"
    return "低"
```

- [ ] **Step 4: Add lead output into `PipelineRunner` result**

In `services/pipeline_runner.py`, after lead generation in `_run_analysis`, include `workbench_candidates` count but do not call Feishu:

```python
result["agent"] = {
    "workbench_candidates": lead_result.qualified_leads + lead_result.needs_enrichment_leads,
}
```

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_agent_runtime.py tests/test_pipeline_runner.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/agent_runtime.py services/pipeline_runner.py tests/test_agent_runtime.py tests/test_pipeline_runner.py
git commit -m "feat: add agent lead prioritizer"
```

---

### Task 3: Feishu Bitable Client With Dry-Run

**Files:**
- Create: `integrations/feishu/bitable.py`
- Modify: `integrations/feishu/__init__.py`
- Modify: `.env.example`
- Test: `tests/test_feishu_bitable_sync.py`

**Interfaces:**
- Produces: `class FeishuBitableSettings`
- Produces: `class FeishuBitableClient`
- Produces: `FeishuBitableClient.upsert_record(record_id: str | None, fields: dict[str, Any]) -> FeishuBitableWriteResult`
- Produces: `FeishuBitableClient.list_records() -> list[dict[str, Any]]`

- [ ] **Step 1: Write failing tests for dry-run client**

Create `tests/test_feishu_bitable_sync.py`:

```python
from integrations.feishu.bitable import FeishuBitableClient, FeishuBitableSettings


def test_bitable_client_dry_run_returns_payload_without_network() -> None:
    client = FeishuBitableClient(settings=FeishuBitableSettings(enabled=False, app_id=None, app_secret=None, app_token=None, table_id=None))

    result = client.upsert_record(None, {"客户": "福州家长", "状态": "待确认"})

    assert result.dry_run is True
    assert result.record_id is None
    assert result.payload["fields"]["客户"] == "福州家长"


def test_bitable_settings_from_env_reads_table(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_ENABLED", "true")
    monkeypatch.setenv("FEISHU_APP_ID", "cli_xxx")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "base_token")
    monkeypatch.setenv("FEISHU_LEADS_TABLE_ID", "tbl123")

    settings = FeishuBitableSettings.from_env()

    assert settings.enabled is True
    assert settings.app_token == "base_token"
    assert settings.table_id == "tbl123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_feishu_bitable_sync.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'integrations.feishu.bitable'`.

- [ ] **Step 3: Implement `integrations/feishu/bitable.py`**

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class FeishuBitableSettings:
    enabled: bool
    app_id: str | None
    app_secret: str | None
    app_token: str | None
    table_id: str | None
    timeout_seconds: float = 10
    page_size: int = 100

    @classmethod
    def from_env(cls) -> "FeishuBitableSettings":
        return cls(
            enabled=_env_bool("FEISHU_ENABLED", default=False) and not _env_bool("FEISHU_SYNC_DRY_RUN", default=False),
            app_id=_empty_to_none(os.getenv("FEISHU_APP_ID")),
            app_secret=_empty_to_none(os.getenv("FEISHU_APP_SECRET")),
            app_token=_empty_to_none(os.getenv("FEISHU_BITABLE_APP_TOKEN")),
            table_id=_empty_to_none(os.getenv("FEISHU_LEADS_TABLE_ID")),
            timeout_seconds=float(os.getenv("FEISHU_TIMEOUT_SECONDS", "10")),
            page_size=int(os.getenv("FEISHU_SYNC_PAGE_SIZE", "100")),
        )


@dataclass(frozen=True, slots=True)
class FeishuBitableWriteResult:
    record_id: str | None
    dry_run: bool
    payload: dict[str, Any]
    response_json: dict[str, Any] | None = None


class FeishuBitableError(RuntimeError):
    pass


class FeishuBitableClient:
    def __init__(self, *, settings: FeishuBitableSettings | None = None, http_client: httpx.Client | None = None) -> None:
        self.settings = settings or FeishuBitableSettings.from_env()
        self._client = http_client or httpx.Client()
        self._tenant_token: str | None = None

    def close(self) -> None:
        self._client.close()

    def upsert_record(self, record_id: str | None, fields: dict[str, Any]) -> FeishuBitableWriteResult:
        payload = {"fields": fields}
        if not self._ready():
            return FeishuBitableWriteResult(record_id=record_id, dry_run=True, payload=payload)
        if record_id:
            url = self._record_url(record_id)
            response = self._client.put(url, json=payload, headers=self._headers(), timeout=self.settings.timeout_seconds)
        else:
            url = self._records_url()
            response = self._client.post(url, json=payload, headers=self._headers(), timeout=self.settings.timeout_seconds)
        data = _json(response)
        if response.status_code >= 300 or data.get("code", 0) != 0:
            raise FeishuBitableError(f"Feishu Bitable write failed: {data}")
        new_record_id = record_id or data.get("data", {}).get("record", {}).get("record_id")
        return FeishuBitableWriteResult(record_id=new_record_id, dry_run=False, payload=payload, response_json=data)

    def list_records(self) -> list[dict[str, Any]]:
        if not self._ready():
            return []
        response = self._client.get(self._records_url(), headers=self._headers(), timeout=self.settings.timeout_seconds)
        data = _json(response)
        if response.status_code >= 300 or data.get("code", 0) != 0:
            raise FeishuBitableError(f"Feishu Bitable list failed: {data}")
        return list(data.get("data", {}).get("items") or [])

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._tenant_access_token()}", "Content-Type": "application/json; charset=utf-8"}

    def _tenant_access_token(self) -> str:
        if self._tenant_token:
            return self._tenant_token
        response = self._client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.settings.app_id, "app_secret": self.settings.app_secret},
            timeout=self.settings.timeout_seconds,
        )
        data = _json(response)
        token = data.get("tenant_access_token")
        if response.status_code >= 300 or not token:
            raise FeishuBitableError(f"Feishu token request failed: {data}")
        self._tenant_token = str(token)
        return self._tenant_token

    def _records_url(self) -> str:
        return f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.settings.app_token}/tables/{self.settings.table_id}/records"

    def _record_url(self, record_id: str) -> str:
        return f"{self._records_url()}/{record_id}"

    def _ready(self) -> bool:
        return bool(self.settings.enabled and self.settings.app_id and self.settings.app_secret and self.settings.app_token and self.settings.table_id)


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise FeishuBitableError("Feishu returned non-JSON response") from exc
    return data if isinstance(data, dict) else {}


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
```

- [ ] **Step 4: Export Bitable client**

Add to `integrations/feishu/__init__.py`:

```python
from integrations.feishu.bitable import (
    FeishuBitableClient,
    FeishuBitableError,
    FeishuBitableSettings,
    FeishuBitableWriteResult,
)
```

- [ ] **Step 5: Update `.env.example`**

Add:

```text
FEISHU_BITABLE_APP_TOKEN=
FEISHU_LEADS_TABLE_ID=
FEISHU_SYNC_DRY_RUN=true
FEISHU_SYNC_PAGE_SIZE=100
```

- [ ] **Step 6: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_feishu_bitable_sync.py tests/test_feishu_transport_callbacks.py -q`

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

```bash
git add integrations/feishu/bitable.py integrations/feishu/__init__.py .env.example tests/test_feishu_bitable_sync.py
git commit -m "feat: add feishu bitable dry-run client"
```

---

### Task 4: Feishu Workbench Mapping and Idempotent Sync

**Files:**
- Modify: `storage/models.py`
- Create: `alembic/versions/0008_feishu_bitable_sync.py`
- Create: `services/feishu_workbench.py`
- Modify: `tests/test_feishu_bitable_sync.py`

**Interfaces:**
- Produces: `class FeishuBitableRecord(Base)`
- Produces: `build_workbench_fields(row: AgentLeadRow) -> dict[str, Any]`
- Produces: `sync_workbench_rows(session: Session, client: FeishuBitableClient, rows: list[AgentLeadRow]) -> FeishuWorkbenchSyncResult`

- [ ] **Step 1: Add failing mapping test**

Append to `tests/test_feishu_bitable_sync.py`:

```python
from services.agent_runtime import AgentLeadRow
from services.feishu_workbench import build_workbench_fields


def test_workbench_fields_are_human_readable() -> None:
    row = AgentLeadRow(
        lead_id=1,
        customer="福州家长",
        need="孩子PET二刷需要冲刺",
        product="PET",
        intent_level="高",
        reason="明确询问二刷冲刺班",
        next_step="先确认考试时间",
        status_label="待确认",
        source_url="https://www.xiaohongshu.com/example",
        discovered_at="2026-07-04T10:00:00+08:00",
    )

    fields = build_workbench_fields(row)

    assert fields["客户"] == "福州家长"
    assert fields["需求"] == "孩子PET二刷需要冲刺"
    assert fields["状态"] == "待确认"
    assert "needs_enrichment" not in str(fields)
    assert "lead_evidence" not in str(fields)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_feishu_bitable_sync.py::test_workbench_fields_are_human_readable -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'services.feishu_workbench'`.

- [ ] **Step 3: Add model and migration**

Add these columns to `Lead` in `storage/models.py` after `recommended_next_step`:

```python
    owner_name: Mapped[str | None] = mapped_column(String(255))
    operator_note: Mapped[str | None] = mapped_column(Text)
    last_feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

Add this class to `storage/models.py` after `EnrichmentTask`:

```python
class FeishuBitableRecord(TimestampMixin, Base):
    __tablename__ = "feishu_bitable_records"
    __table_args__ = (
        UniqueConstraint("local_entity_type", "local_entity_id", "app_token", "table_id", name="uq_feishu_bitable_local_record"),
        Index("ix_feishu_bitable_record_id", "record_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    local_entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    local_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    app_token: Mapped[str] = mapped_column(String(255), nullable=False)
    table_id: Mapped[str] = mapped_column(String(255), nullable=False)
    record_id: Mapped[str | None] = mapped_column(String(255))
    sync_direction: Mapped[str] = mapped_column(String(50), nullable=False, default="push", server_default="push")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_remote_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    remote_fields_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
```

Create `alembic/versions/0008_feishu_bitable_sync.py`:

```python
"""feishu bitable sync

Revision ID: 0008_feishu_bitable_sync
Revises: 0007_leads_business_objects
Create Date: 2026-07-04 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_feishu_bitable_sync"
down_revision: str | None = "0007_leads_business_objects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("owner_name", sa.String(length=255), nullable=True))
    op.add_column("leads", sa.Column("operator_note", sa.Text(), nullable=True))
    op.add_column("leads", sa.Column("last_feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "feishu_bitable_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("local_entity_type", sa.String(length=50), nullable=False),
        sa.Column("local_entity_id", sa.Integer(), nullable=False),
        sa.Column("app_token", sa.String(length=255), nullable=False),
        sa.Column("table_id", sa.String(length=255), nullable=False),
        sa.Column("record_id", sa.String(length=255), nullable=True),
        sa.Column("sync_direction", sa.String(length=50), server_default="push", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_remote_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=50), server_default="pending", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("remote_fields_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "local_entity_type",
            "local_entity_id",
            "app_token",
            "table_id",
            name="uq_feishu_bitable_local_record",
        ),
    )
    op.create_index("ix_feishu_bitable_record_id", "feishu_bitable_records", ["record_id"])


def downgrade() -> None:
    op.drop_index("ix_feishu_bitable_record_id", table_name="feishu_bitable_records")
    op.drop_table("feishu_bitable_records")
    op.drop_column("leads", "last_feedback_at")
    op.drop_column("leads", "operator_note")
    op.drop_column("leads", "owner_name")
```

- [ ] **Step 4: Implement `services/feishu_workbench.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from integrations.feishu.bitable import FeishuBitableClient
from services.agent_runtime import AgentLeadRow
from storage.models import FeishuBitableRecord


@dataclass(frozen=True, slots=True)
class FeishuWorkbenchSyncResult:
    created: int = 0
    updated: int = 0
    dry_run: int = 0
    failed: int = 0


def build_workbench_fields(row: AgentLeadRow) -> dict[str, Any]:
    return {
        "客户": row.customer,
        "需求": row.need,
        "课程/考试": row.product,
        "意向程度": row.intent_level,
        "为什么推荐": row.reason,
        "下一步": row.next_step,
        "状态": row.status_label,
        "来源链接": row.source_url,
        "发现时间": row.discovered_at,
    }


def sync_workbench_rows(session: Session, client: FeishuBitableClient, rows: list[AgentLeadRow]) -> FeishuWorkbenchSyncResult:
    counts = {"created": 0, "updated": 0, "dry_run": 0, "failed": 0}
    app_token = client.settings.app_token or "dry-run-app"
    table_id = client.settings.table_id or "dry-run-table"
    now = datetime.now(UTC)
    for row in rows:
        mapping = _get_or_create_mapping(session, row.lead_id, app_token=app_token, table_id=table_id)
        fields = build_workbench_fields(row)
        try:
            result = client.upsert_record(mapping.record_id, fields)
        except Exception as exc:
            mapping.last_sync_status = "failed"
            mapping.last_error = str(exc)
            counts["failed"] += 1
            continue
        if result.dry_run:
            counts["dry_run"] += 1
        elif mapping.record_id:
            counts["updated"] += 1
        else:
            counts["created"] += 1
        mapping.record_id = result.record_id or mapping.record_id
        mapping.remote_fields_json = fields
        mapping.last_synced_at = now
        mapping.last_sync_status = "dry_run" if result.dry_run else "synced"
        mapping.last_error = None
    session.flush()
    return FeishuWorkbenchSyncResult(**counts)


def _get_or_create_mapping(session: Session, lead_id: int, *, app_token: str, table_id: str) -> FeishuBitableRecord:
    mapping = session.scalar(
        select(FeishuBitableRecord).where(
            FeishuBitableRecord.local_entity_type == "lead",
            FeishuBitableRecord.local_entity_id == lead_id,
            FeishuBitableRecord.app_token == app_token,
            FeishuBitableRecord.table_id == table_id,
        )
    )
    if mapping is not None:
        return mapping
    mapping = FeishuBitableRecord(
        local_entity_type="lead",
        local_entity_id=lead_id,
        app_token=app_token,
        table_id=table_id,
        sync_direction="push",
        last_sync_status="pending",
    )
    session.add(mapping)
    session.flush()
    return mapping
```

- [ ] **Step 5: Add idempotent sync test**

Append to `tests/test_feishu_bitable_sync.py`:

```python
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from integrations.feishu.bitable import FeishuBitableClient
from services.feishu_workbench import sync_workbench_rows
from storage.database import Base
from storage.models import FeishuBitableRecord


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield SessionLocal
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_sync_workbench_rows_is_idempotent(factory: sessionmaker[Session]) -> None:
    row = AgentLeadRow(
        lead_id=1,
        customer="福州家长",
        need="孩子PET二刷需要冲刺",
        product="PET",
        intent_level="高",
        reason="明确询问二刷冲刺班",
        next_step="先确认考试时间",
        status_label="待确认",
        source_url="",
        discovered_at="2026-07-04T10:00:00+08:00",
    )
    client = FeishuBitableClient(settings=FeishuBitableSettings(enabled=False, app_id=None, app_secret=None, app_token="app", table_id="tbl"))

    with factory() as session:
        first = sync_workbench_rows(session, client, [row])
        second = sync_workbench_rows(session, client, [row])
        session.commit()

    assert first.dry_run == 1
    assert second.dry_run == 1
    with factory() as session:
        assert session.query(FeishuBitableRecord).count() == 1
```

- [ ] **Step 6: Run migration and tests**

Run:

```bash
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest tests/test_feishu_bitable_sync.py tests/test_core_data_models.py -q
```

Expected: migration succeeds and tests pass.

- [ ] **Step 7: Commit**

```bash
git add storage/models.py alembic/versions/0008_feishu_bitable_sync.py services/feishu_workbench.py tests/test_feishu_bitable_sync.py
git commit -m "feat: sync leads to feishu workbench"
```

---

### Task 5: CLI Integration and Feishu Feedback Pull

**Files:**
- Modify: `apps/cli.py`
- Modify: `services/feishu_workbench.py`
- Test: `tests/test_feishu_bitable_sync.py`
- Test: `tests/test_agent_runtime.py`

**Interfaces:**
- Produces CLI: `python -m apps.cli --json agent-run`
- Produces CLI: `python -m apps.cli --json feishu-sync`
- Produces CLI: `python -m apps.cli --json feishu-pull-feedback`
- Produces: `pull_workbench_feedback(session: Session, client: FeishuBitableClient) -> dict[str, int]`

- [ ] **Step 1: Add feedback pull test**

Append to `tests/test_feishu_bitable_sync.py`:

```python
from services.feishu_workbench import pull_workbench_feedback
from storage.models import FeishuBitableRecord, Lead, PublicProfile


class FakeListClient:
    settings = FeishuBitableSettings(enabled=False, app_id=None, app_secret=None, app_token="app", table_id="tbl")

    def list_records(self):
        return [{"record_id": "rec1", "fields": {"状态": "不合适", "负责人": "小王", "备注": "广告号"}}]


def test_pull_feedback_updates_manual_status(factory) -> None:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="u1", display_name="客户")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="needs_enrichment")
        session.add(lead)
        session.flush()
        session.add(FeishuBitableRecord(
            local_entity_type="lead",
            local_entity_id=lead.id,
            app_token="app",
            table_id="tbl",
            record_id="rec1",
            last_sync_status="synced",
        ))
        session.commit()

    with factory() as session:
        result = pull_workbench_feedback(session, FakeListClient())
        session.commit()

    assert result["updated"] == 1
    with factory() as session:
        lead = session.get(Lead, 1)
        assert lead is not None
        assert lead.status == "ignored"
```

- [ ] **Step 2: Implement feedback pull**

Add to `services/feishu_workbench.py`. Also add `Lead` to the model imports at the top:

```python
from storage.models import FeishuBitableRecord, Lead
```

Then add:

```python
STATUS_FROM_FEISHU = {
    "新发现": "new",
    "待确认": "needs_enrichment",
    "可跟进": "qualified",
    "已跟进": "handled",
    "不合适": "ignored",
}


def pull_workbench_feedback(session: Session, client: FeishuBitableClient) -> dict[str, int]:
    updated = 0
    skipped = 0
    records = client.list_records()
    app_token = client.settings.app_token or "dry-run-app"
    table_id = client.settings.table_id or "dry-run-table"
    for record in records:
        record_id = str(record.get("record_id") or "")
        fields = record.get("fields") or {}
        status_label = fields.get("状态")
        mapping = session.scalar(
            select(FeishuBitableRecord).where(
                FeishuBitableRecord.app_token == app_token,
                FeishuBitableRecord.table_id == table_id,
                FeishuBitableRecord.record_id == record_id,
            )
        )
        if mapping is None or status_label not in STATUS_FROM_FEISHU:
            skipped += 1
            continue
        lead = session.get(Lead, mapping.local_entity_id)
        if lead is None:
            skipped += 1
            continue
        lead.status = STATUS_FROM_FEISHU[str(status_label)]
        lead.owner_name = fields.get("负责人") or lead.owner_name
        lead.operator_note = fields.get("备注") or lead.operator_note
        lead.last_feedback_at = datetime.now(UTC)
        mapping.remote_fields_json = dict(fields)
        mapping.last_sync_status = "feedback_pulled"
        updated += 1
    session.flush()
    return {"updated": updated, "skipped": skipped}
```

- [ ] **Step 3: Add CLI commands**

In `apps/cli.py`, add parsers:

```python
subparsers.add_parser("agent-run", help="Run agent-selected collection and sync-ready prioritization.")
subparsers.add_parser("feishu-sync", help="Sync prioritized leads to Feishu Bitable.")
subparsers.add_parser("feishu-pull-feedback", help="Pull Feishu Bitable status changes back into PostgreSQL.")
```

Add command branches:

```python
elif args.command == "agent-run":
    payload = run_agent_cycle(SessionLocal, runner)
elif args.command == "feishu-sync":
    with SessionLocal() as session:
        rows = rank_leads_for_workbench(session)
        client = FeishuBitableClient()
        result = sync_workbench_rows(session, client, rows)
        session.commit()
        payload = {"feishu_sync": result.__dict__}
elif args.command == "feishu-pull-feedback":
    with SessionLocal() as session:
        client = FeishuBitableClient()
        payload = {"feishu_feedback": pull_workbench_feedback(session, client)}
        session.commit()
```

Import:

```python
from integrations.feishu.bitable import FeishuBitableClient
from services.agent_runtime import rank_leads_for_workbench, run_agent_cycle
from services.feishu_workbench import pull_workbench_feedback, sync_workbench_rows
```

- [ ] **Step 4: Run CLI dry-run locally**

Run:

```bash
.venv/bin/python -m apps.cli --json feishu-sync
.venv/bin/python -m apps.cli --json feishu-pull-feedback
```

Expected: both commands exit `0`. `feishu-sync` reports `dry_run` when real credentials are not configured. `feishu-pull-feedback` reports zero updates when no remote records are available.

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_feishu_bitable_sync.py tests/test_agent_runtime.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/cli.py services/feishu_workbench.py tests/test_feishu_bitable_sync.py tests/test_agent_runtime.py
git commit -m "feat: add agent and feishu sync cli"
```

---

### Task 6: Real Feishu Setup Gate, Verification, and Docs

**Files:**
- Modify: `HANDOFF.md`
- Modify: `PROJECT_DASHBOARD.md`
- Modify: `TASKS.md`
- Modify: `docs/ARCHITECTURE.md`
- Create: `docs/reports/FEISHU_WORKBENCH_VERIFICATION.md`

**Interfaces:**
- Consumes: CLI commands from Task 5.
- Produces: documented setup and verification result.

- [ ] **Step 1: Stop and request user help for Feishu credentials**

Ask the user for these values before running a real sync:

```text
1. 飞书自建应用的 APP_ID
2. 飞书自建应用的 APP_SECRET
3. 多维表格 app_token
4. “客户跟进表”的 table_id
5. 确认应用已经有多维表格读写权限，并已安装到对应飞书空间
```

Do not ask the user for these in chat if they prefer entering them locally. They can set them in `.env` or shell environment:

```bash
export FEISHU_ENABLED=true
export FEISHU_SYNC_DRY_RUN=false
export FEISHU_APP_ID="replace_with_feishu_app_id"
export FEISHU_APP_SECRET="replace_with_feishu_app_secret"
export FEISHU_BITABLE_APP_TOKEN="replace_with_bitable_app_token"
export FEISHU_LEADS_TABLE_ID="replace_with_customer_table_id"
```

- [ ] **Step 2: Verify dry-run before real sync**

Run:

```bash
FEISHU_SYNC_DRY_RUN=true .venv/bin/python -m apps.cli --json feishu-sync
```

Expected: command exits `0` and reports records that would be synced without network writes.

- [ ] **Step 3: Verify real sync only after user confirms credentials**

Run:

```bash
FEISHU_ENABLED=true FEISHU_SYNC_DRY_RUN=false .venv/bin/python -m apps.cli --json feishu-sync
```

Expected: command exits `0`, writes or updates rows in `客户跟进表`, and returns created/updated counts.

- [ ] **Step 4: Verify feedback pull**

In Feishu, manually set one row `状态` to `不合适` and add `负责人` plus `备注`. Then run:

```bash
FEISHU_ENABLED=true FEISHU_SYNC_DRY_RUN=false .venv/bin/python -m apps.cli --json feishu-pull-feedback
```

Expected: command exits `0`, reports at least one updated record, and local `leads.status` becomes `ignored` for that lead.

- [ ] **Step 5: Write verification report**

Create `docs/reports/FEISHU_WORKBENCH_VERIFICATION.md` with actual values from this run. Use this exact structure and replace each value with command output, not guesses:

````markdown
# Feishu Workbench Verification

## Environment

- Branch: feat/v15-agent-neutral-runtime
- Commit: output of `git rev-parse --short HEAD`
- Feishu sync mode: dry-run or real, based on the command that was executed
- Table name: 客户跟进表

## Commands

```bash
.venv/bin/python -m apps.cli --json feishu-sync
.venv/bin/python -m apps.cli --json feishu-pull-feedback
```

## Result

- Rows created: integer from `feishu_sync.created`
- Rows updated: integer from `feishu_sync.updated`
- Feedback rows pulled: integer from `feishu_feedback.updated`
- Known issues: one sentence describing the real blocker, or `None observed during this run`
````

- [ ] **Step 6: Update project state docs**

Update `TASKS.md`, `PROJECT_DASHBOARD.md`, `HANDOFF.md`, and `docs/ARCHITECTURE.md` to say:

- The main user workspace is Feishu `客户跟进表`.
- HTML pages are retained as optional debug/local tools.
- PostgreSQL remains the master database.
- Real Feishu status is either verified or blocked with the exact missing credential/permission.

- [ ] **Step 7: Run full verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/alembic current
git status --short
```

Expected:

- pytest passes.
- Alembic reports `0008_feishu_bitable_sync (head)`.
- `git status --short` shows only intended doc/report changes before commit.

- [ ] **Step 8: Commit**

```bash
git add HANDOFF.md PROJECT_DASHBOARD.md TASKS.md docs/ARCHITECTURE.md docs/reports/FEISHU_WORKBENCH_VERIFICATION.md
git commit -m "docs: record feishu workbench verification"
```

---

## Self-Review

- Spec coverage: The plan covers one Feishu table, PostgreSQL master storage, agent query/lead prioritization, dry-run and real Feishu sync, feedback readback, demand-recognition improvements, and keeping HTML as optional debug tooling.
- User-help gate: Task 6 explicitly stops for user-provided Feishu app credentials, app token, table ID, and permission confirmation before real sync.
- Type consistency: `AgentLeadRow`, `FeishuBitableClient`, `FeishuBitableRecord`, `sync_workbench_rows`, and `pull_workbench_feedback` are introduced before use.
- Scope: The plan does not implement automatic private messaging, automatic comments, multi-table Feishu structure, or rule self-modification.
