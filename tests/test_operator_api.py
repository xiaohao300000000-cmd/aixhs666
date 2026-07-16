from __future__ import annotations

from collections.abc import Iterator
import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.main import create_app
from services.customer_progression import CustomerProgressionResult
from services.customer_crm_sync import CustomerCrmSyncResult
from storage.database import Base, get_session
from storage.models import CollectionTask, ContactCommandOperation, Lead, LeadCommentReply, PublicProfile


@pytest.fixture()
def operator_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("OPS_TOKEN", "operator-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app = create_app()
    app.state.operator_test_session_factory = session_factory
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_operator_workbench_rejects_missing_token(operator_client: TestClient) -> None:
    response = operator_client.get("/operator/api/workbench")

    assert response.status_code == 401


def test_operator_workbench_rejects_wrong_token(operator_client: TestClient) -> None:
    response = operator_client.get(
        "/operator/api/workbench",
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status_code == 401


def test_operator_workbench_returns_aggregate(operator_client: TestClient) -> None:
    response = operator_client.get(
        "/operator/api/workbench",
        headers={"Authorization": "Bearer operator-secret"},
    )

    assert response.status_code == 200
    assert response.json()["attention"]["review_queue"] == 0
    assert response.json()["next_action"]["kind"] == "none"


def test_operator_workbench_accepts_compatibility_header(operator_client: TestClient) -> None:
    response = operator_client.get(
        "/operator/api/workbench",
        headers={"X-Ops-Token": "operator-secret"},
    )

    assert response.status_code == 200


def test_operator_leads_and_tasks_require_same_token(operator_client: TestClient) -> None:
    missing_leads = operator_client.get("/operator/api/leads")
    missing_tasks = operator_client.get("/operator/api/tasks")
    headers = {"Authorization": "Bearer operator-secret"}

    leads = operator_client.get("/operator/api/leads", headers=headers)
    tasks = operator_client.get("/operator/api/tasks", headers=headers)

    assert missing_leads.status_code == 401
    assert missing_tasks.status_code == 401
    assert leads.status_code == 200
    assert tasks.status_code == 200


def test_operator_promote_returns_structured_consequences(
    operator_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def progress(_session: Session, lead_id: int, **kwargs: object) -> CustomerProgressionResult:
        calls.append({"lead_id": lead_id, **kwargs})
        return CustomerProgressionResult(
            customer_id=lead_id,
            customer_stage="awaiting_first_contact",
            next_action="prepare_public_reply",
            timeline_event_id=91,
            timeline_event_type="candidate_promoted",
            screening_id=17,
            idempotent_replay=False,
        )

    monkeypatch.setattr("apps.api.routes.operator_api.progress_operator_lead", progress)
    monkeypatch.setattr("apps.api.routes.operator_api.get_operator_lead", lambda _session, lead_id: {"id": lead_id})

    response = operator_client.post(
        "/operator/api/leads/151/review",
        headers={"Authorization": "Bearer operator-secret"},
        json={
            "action": "promote",
            "reason": "需求明确",
            "reviewer_id": "operator-1",
            "idempotency_key": "ui-review-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["lead"] == {"id": 151}
    assert response.json()["progression"]["customer_stage"] == "awaiting_first_contact"
    assert response.json()["progression"]["next_action"] == "prepare_public_reply"
    assert calls[0]["action"] == "promote"
    assert calls[0]["idempotency_key"] == "ui-review-1"


def test_operator_customer_routes_and_sync_require_idempotency_key(
    operator_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"Authorization": "Bearer operator-secret"}
    monkeypatch.setattr(
        "apps.api.routes.operator_api.list_operator_customers",
        lambda _session, **_kwargs: {"items": [{"customer_id": 151}], "count": 1},
    )
    monkeypatch.setattr(
        "apps.api.routes.operator_api.get_operator_customer",
        lambda _session, customer_id: {"customer_id": customer_id},
    )
    monkeypatch.setattr(
        "apps.api.routes.operator_api.get_operator_customer_timeline",
        lambda _session, customer_id: {"customer_id": customer_id, "items": []},
    )
    sync_calls: list[list[int] | None] = []

    def sync(_factory, *, customer_ids=None):
        sync_calls.append(customer_ids)
        return CustomerCrmSyncResult(status="synced", customers_synced=1)

    monkeypatch.setattr("apps.api.routes.operator_api.sync_customer_crm", sync)

    listing = operator_client.get("/operator/api/customers", headers=headers)
    detail = operator_client.get("/operator/api/customers/151", headers=headers)
    timeline = operator_client.get("/operator/api/customers/151/timeline", headers=headers)
    missing_key = operator_client.post("/operator/api/customers/sync", headers=headers, json={})
    synced = operator_client.post(
        "/operator/api/customers/sync",
        headers=headers,
        json={"customer_ids": [151], "idempotency_key": "customer-sync-1"},
    )

    assert listing.status_code == 200
    assert detail.json()["customer_id"] == 151
    assert timeline.json()["items"] == []
    assert missing_key.status_code == 422
    assert synced.status_code == 200
    assert synced.json()["idempotency_key"] == "customer-sync-1"
    assert synced.json()["sync"]["customers_synced"] == 1
    assert sync_calls == [[151]]


def test_operator_contact_routes_preserve_two_step_contract(
    operator_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"Authorization": "Bearer operator-secret"}
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "apps.api.routes.operator_api.get_operator_contact_attempt",
        lambda _session, customer_id: {"attempt_id": 41, "customer_id": customer_id, "status": "awaiting_approval"},
    )
    monkeypatch.setattr(
        "apps.api.routes.operator_api.require_operator_contact_attempt",
        lambda _session, **_kwargs: object(),
    )

    def command(name: str):
        def invoke(_session, **kwargs):
            calls.append((name, kwargs))
            return {"attempt_id": kwargs.get("reply_id"), "status": "approved" if name == "approve" else "queued"}
        return invoke

    monkeypatch.setattr("apps.api.routes.operator_api.edit_contact_draft", command("edit"))
    monkeypatch.setattr("apps.api.routes.operator_api.approve_contact_draft", command("approve"))
    monkeypatch.setattr("apps.api.routes.operator_api.send_approved_contact", command("send"))

    read = operator_client.get("/operator/api/customers/151/contact-attempt", headers=headers)
    edited = operator_client.put(
        "/operator/api/customers/151/contact-attempt/41/draft",
        headers=headers,
        json={"draft_revision": 1, "text": "修改草稿", "operator": "op", "idempotency_key": "edit-1"},
    )
    approved = operator_client.post(
        "/operator/api/customers/151/contact-attempt/41/approve",
        headers=headers,
        json={"draft_revision": 2, "operator": "op", "idempotency_key": "approve-1"},
    )
    sent = operator_client.post(
        "/operator/api/customers/151/contact-attempt/41/send",
        headers=headers,
        json={"draft_revision": 2, "confirmed": True, "operator": "op", "idempotency_key": "send-1"},
    )

    assert read.status_code == 200 and read.json()["status"] == "awaiting_approval"
    assert edited.status_code == 200
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    assert sent.status_code == 200 and sent.json()["status"] == "queued"
    assert [name for name, _ in calls] == ["edit", "approve", "send"]


def test_miaoda_bff_contact_json_is_accepted_by_real_fastapi_commands(operator_client: TestClient) -> None:
    factory = operator_client.app.state.operator_test_session_factory
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="miaoda-contract")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
        session.add(lead)
        session.flush()
        reply = LeadCommentReply(
            lead_id=lead.id,
            target_platform_comment_id="comment-miaoda-contract",
            target_platform_content_id="note-miaoda-contract",
            target_url="https://www.xiaohongshu.com/explore/note-miaoda-contract",
            draft_text="原始草稿",
            status="awaiting_approval",
        )
        unknown = LeadCommentReply(
            lead_id=lead.id,
            target_platform_comment_id="comment-miaoda-unknown",
            target_platform_content_id="note-miaoda-unknown",
            draft_text="待核验草稿",
            approved_text="待核验草稿",
            approved_revision=1,
            attempt_count=1,
            status="result_unknown",
        )
        session.add_all([reply, unknown])
        session.commit()
        customer_id, reply_id, unknown_id = lead.id, reply.id, unknown.id

    headers = {"Authorization": "Bearer operator-secret"}
    edited = operator_client.put(
        f"/operator/api/customers/{customer_id}/contact-attempt/{reply_id}/draft",
        headers=headers,
        json={"draft_revision": 1, "text": "修改后的公开回复", "operator": "miaoda-operator", "idempotency_key": "edit-contract"},
    )
    approved = operator_client.post(
        f"/operator/api/customers/{customer_id}/contact-attempt/{reply_id}/approve",
        headers=headers,
        json={"draft_revision": 2, "operator": "miaoda-operator", "idempotency_key": "approve-contract"},
    )
    sent = operator_client.post(
        f"/operator/api/customers/{customer_id}/contact-attempt/{reply_id}/send",
        headers=headers,
        json={"draft_revision": 2, "confirmed": True, "operator": "miaoda-operator", "idempotency_key": "send-contract"},
    )
    recovered = operator_client.post(
        f"/operator/api/customers/{customer_id}/contact-attempt/{unknown_id}/confirm-not-sent",
        headers=headers,
        json={"operator": "miaoda-operator", "reason": "人工核验目标页面未发送", "idempotency_key": "recover-contract"},
    )

    assert [edited.status_code, approved.status_code, sent.status_code, recovered.status_code] == [200, 200, 200, 200]
    assert edited.json()["draft_revision"] == 2
    assert approved.json()["status"] == "approved"
    assert sent.json()["status"] == "queued"
    assert recovered.json()["status"] == "failed"


def test_prepare_api_replay_reports_sanitized_worker_failure(operator_client: TestClient) -> None:
    factory = operator_client.app.state.operator_test_session_factory
    key = "prepare-api-failed"
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="prepare-api-failed")
        session.add(profile)
        session.flush()
        lead = Lead(platform="xhs", public_profile_id=profile.id, status="qualified")
        task = CollectionTask(
            task_type="comment_reply_prepare",
            platform="xhs",
            target_id="pending",
            status="failed",
            last_error="Traceback bearer=secret CDP cookie=session at /private/path",
        )
        session.add_all([lead, task])
        session.flush()
        task.target_id = str(lead.id)
        session.add(
            ContactCommandOperation(
                operation_scope="prepare_contact_draft",
                entity_id=lead.id,
                idempotency_key_hash=hashlib.sha256(key.encode()).hexdigest(),
                request_json={"customer_id": lead.id},
                result_json={"status": "queued", "customer_id": lead.id, "screening_id": 9, "task_id": task.id},
            )
        )
        session.commit()
        customer_id = lead.id

    response = operator_client.post(
        f"/operator/api/customers/{customer_id}/contact-attempt/prepare",
        headers={"Authorization": "Bearer operator-secret"},
        json={"idempotency_key": key},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "queued",
        "customer_id": customer_id,
        "screening_id": 9,
        "task_id": task.id,
        "task_status": "failed",
        "failure_reason": "草稿生成失败，请检查任务中心后重新生成。",
    }


def test_operator_run_report_candidate_and_review_queue_routes_require_stable_contracts(
    operator_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"Authorization": "Bearer operator-secret"}
    monkeypatch.setattr(
        "apps.api.routes.operator_api.get_operator_run_report",
        lambda _session, run_id, **kwargs: {
            "run_id": run_id,
            "conclusion": "发现候选",
            "counts": {"priority_review": 1},
            "next_action": {"label": "审核本次候选"},
            "rebuild": kwargs.get("rebuild", False),
        },
    )
    monkeypatch.setattr(
        "apps.api.routes.operator_api.list_operator_run_candidates",
        lambda _session, run_id, **kwargs: {
            "run_id": run_id,
            "layer": kwargs.get("layer"),
            "count": 1,
            "items": [{"candidate_key": "profile:1", "layer": kwargs.get("layer")}],
        },
    )
    monkeypatch.setattr(
        "apps.api.routes.operator_api.prepare_operator_review_queue",
        lambda _session, run_id, **kwargs: {
            "run_id": run_id,
            "idempotency_key": kwargs["idempotency_key"],
            "queue_date": kwargs["queue_date"].isoformat(),
            "item_ids": [1],
        },
    )
    monkeypatch.setattr(
        "apps.api.routes.operator_api.get_operator_review_queue",
        lambda _session, **kwargs: {
            "queue_date": kwargs["queue_date"].isoformat(),
            "total": 1,
            "items": [{"candidate_key": "profile:1", "layer": kwargs.get("layer")}],
            "progress": {"completed": 0, "target": 1, "pending": 1, "quality_control": 0},
        },
    )
    monkeypatch.setattr(
        "apps.api.routes.operator_api.continue_operator_review_queue",
        lambda _session, **kwargs: {
            "idempotency_key": kwargs["idempotency_key"],
            "priority_only": kwargs["priority_only"],
            "created": kwargs["additional"],
        },
    )

    report = operator_client.get("/operator/api/tasks/runs/8/report", headers=headers)
    candidates = operator_client.get(
        "/operator/api/tasks/runs/8/candidates?layer=automatic_exclusion",
        headers=headers,
    )
    missing_rebuild_key = operator_client.post(
        "/operator/api/tasks/runs/8/report/rebuild", headers=headers, json={}
    )
    rebuilt = operator_client.post(
        "/operator/api/tasks/runs/8/report/rebuild",
        headers=headers,
        json={"idempotency_key": "rebuild-8"},
    )
    missing_prepare_key = operator_client.post(
        "/operator/api/tasks/runs/8/review-queue",
        headers=headers,
        json={"queue_date": "2026-07-16"},
    )
    prepared = operator_client.post(
        "/operator/api/tasks/runs/8/review-queue",
        headers=headers,
        json={"queue_date": "2026-07-16", "idempotency_key": "prepare-8"},
    )
    queue = operator_client.get(
        "/operator/api/review-queue?queue_date=2026-07-16&layer=priority_review",
        headers=headers,
    )
    missing_continue_key = operator_client.post(
        "/operator/api/review-queue/continue", headers=headers, json={}
    )
    continued = operator_client.post(
        "/operator/api/review-queue/continue",
        headers=headers,
        json={
            "queue_date": "2026-07-16",
            "additional": 20,
            "priority_only": True,
            "idempotency_key": "continue-1",
        },
    )

    assert report.status_code == 200
    assert report.json()["next_action"]["label"] == "审核本次候选"
    assert candidates.json()["items"][0]["layer"] == "automatic_exclusion"
    assert missing_rebuild_key.status_code == 422
    assert rebuilt.json()["rebuild"] is True
    assert missing_prepare_key.status_code == 422
    assert prepared.json()["item_ids"] == [1]
    assert queue.json()["progress"]["target"] == 1
    assert missing_continue_key.status_code == 422
    assert continued.json() == {
        "idempotency_key": "continue-1",
        "priority_only": True,
        "created": 20,
    }


def test_review_queue_idempotency_conflict_returns_safe_http_400(
    operator_client: TestClient,
) -> None:
    headers = {"Authorization": "Bearer operator-secret"}
    idempotency_key = "never-echo-this-conflict-key"
    first = operator_client.post(
        "/operator/api/review-queue/continue",
        headers=headers,
        json={
            "queue_date": "2026-07-16",
            "additional": 20,
            "priority_only": False,
            "idempotency_key": idempotency_key,
        },
    )
    conflict = operator_client.post(
        "/operator/api/review-queue/continue",
        headers=headers,
        json={
            "queue_date": "2026-07-16",
            "additional": 21,
            "priority_only": False,
            "idempotency_key": idempotency_key,
        },
    )

    assert first.status_code == 200
    assert conflict.status_code == 400
    assert conflict.json() == {
        "detail": "idempotency key conflicts with an existing operation"
    }
    assert idempotency_key not in conflict.text
