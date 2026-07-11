from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import httpx

from integrations.feishu.bitable import FeishuBitableClient, FeishuBitableSettings, FeishuBitableWriteResult
from services.feishu_customer_followup import pull_customer_followup_edits, push_customer_followup
from storage.database import Base
from storage.models import Comment, Content, FeishuBitableRecord, Lead, LeadCommentReply, LeadScreeningResult, PublicProfile


class FakeBitableClient:
    def __init__(self) -> None:
        self.settings = FeishuBitableSettings(
            enabled=True,
            app_id="app-id",
            app_secret="app-secret",
            app_token="followup-app",
            table_id="followup-table",
        )
        self.upserts: list[tuple[str | None, dict[str, object]]] = []
        self.remote_records: list[dict[str, object]] = []
        self.error: Exception | None = None
        self.search_matches: list[dict[str, object]] = []

    def upsert_record(self, record_id: str | None, fields: dict[str, object]) -> FeishuBitableWriteResult:
        if self.error is not None:
            raise self.error
        self.upserts.append((record_id, fields))
        return FeishuBitableWriteResult(record_id=record_id or "rec-customer", dry_run=False, payload={"fields": fields})

    def list_records(self) -> list[dict[str, object]]:
        if self.error is not None:
            raise self.error
        return self.remote_records

    def find_records_by_exact_field(self, field_name: str, value: str) -> list[dict[str, object]]:
        assert field_name == "客户唯一键"
        assert value == "xhs:user-1"
        return self.search_matches


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    engine.dispose()


def test_push_maps_sent_reply_and_upserts_idempotently(factory: sessionmaker[Session]) -> None:
    lead_id, reply_id = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()

    first = push_customer_followup(factory, reply_id=reply_id, client=client)
    second = push_customer_followup(factory, reply_id=reply_id, client=client)

    assert first.status == second.status == "synced"
    assert client.upserts[0][0] is None
    assert client.upserts[1][0] == "rec-customer"
    assert client.upserts[0][1]["客户唯一键"] == "xhs:user-1"
    assert client.upserts[0][1]["当前客户状态"] == "已评论引导，等待客户私信"
    assert client.upserts[0][1]["评论发送结果"] == "评论成功"
    with factory() as session:
        mappings = session.scalars(select(FeishuBitableRecord)).all()
        assert len(mappings) == 1
        assert mappings[0].local_entity_type == "customer_followup"
        assert mappings[0].local_entity_id == lead_id


def test_push_adopts_preexisting_remote_record_when_mapping_was_lost(factory: sessionmaker[Session]) -> None:
    _, reply_id = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()
    client.search_matches = [{"record_id": "rec-existing", "fields": {"客户唯一键": "xhs:user-1"}}]

    result = push_customer_followup(factory, reply_id=reply_id, client=client)

    assert result.status == "synced"
    assert client.upserts[0][0] == "rec-existing"


def test_push_fails_reconciliation_on_duplicate_remote_customer_keys(factory: sessionmaker[Session]) -> None:
    _, reply_id = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()
    client.search_matches = [
        {"record_id": "rec-1", "fields": {"客户唯一键": "xhs:user-1"}},
        {"record_id": "rec-2", "fields": {"客户唯一键": "xhs:user-1"}},
    ]

    result = push_customer_followup(factory, reply_id=reply_id, client=client)

    assert result.status == "failed"
    assert result.failed == 1
    assert "duplicate" in result.errors[0]
    assert client.upserts == []


def test_pull_accepts_only_human_fields_and_preserves_system_facts(factory: sessionmaker[Session]) -> None:
    lead_id, reply_id = _seed_customer(factory, reply_status="sent", lead_status="qualified")
    client = FakeBitableClient()
    push_customer_followup(factory, reply_id=reply_id, client=client)
    client.remote_records = [
        {
            "record_id": "rec-customer",
            "fields": {
                "客户唯一键": "xhs:user-1",
                "负责人": "小王",
                "运营备注": "客户已主动私信",
                "下次跟进时间": "1784080800000",
                "当前客户状态": "已收到私信",
                "评论发送结果": "未发送",
                "评论回复记录 ID": "999999",
            },
        }
    ]

    result = pull_customer_followup_edits(factory, client=client)

    assert result.status == "synced"
    with factory() as session:
        lead = session.get(Lead, lead_id)
        reply = session.get(LeadCommentReply, reply_id)
        assert lead is not None and reply is not None
        assert lead.followup_status == "已收到私信"
        assert lead.owner_name == "小王"
        assert lead.operator_note == "客户已主动私信"
        assert lead.next_followup_at.isoformat().startswith("2026-07-15T02:00:00")
        assert lead.status == "qualified"
        assert reply.status == "sent"
        mapping = session.scalar(select(FeishuBitableRecord))
        assert mapping.remote_fields_json["评论发送结果"] == "评论成功"
        assert mapping.remote_fields_json["负责人"] == "小王"


def test_datetime_round_trip_uses_epoch_milliseconds_and_shanghai_for_naive_values(factory: sessionmaker[Session]) -> None:
    lead_id, reply_id = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()
    client.remote_records = [
        {
            "record_id": "rec-customer",
            "fields": {"客户唯一键": "xhs:user-1", "当前客户状态": "沟通中", "下次跟进时间": "2026-07-15 10:00:00"},
        }
    ]

    pull_customer_followup_edits(factory, client=client)
    push_customer_followup(factory, reply_id=reply_id, client=client)

    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead.next_followup_at.isoformat().startswith("2026-07-15T02:00:00")
    assert client.upserts[-1][1]["下次跟进时间"] == 1784080800000


def test_lark_cli_push_formats_datetime_as_documented_local_string(factory: sessionmaker[Session]) -> None:
    _, reply_id = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()
    client.settings = _client_settings(transport="lark_cli")
    client.remote_records = [{"record_id": "rec", "fields": {"客户唯一键": "xhs:user-1", "当前客户状态": "沟通中", "下次跟进时间": 1784080800000}}]
    pull_customer_followup_edits(factory, client=client)

    push_customer_followup(factory, reply_id=reply_id, client=client)

    assert client.upserts[-1][1]["下次跟进时间"] == "2026-07-15 10:00:00"


def test_pull_accepts_numeric_epoch_and_preserves_remote_update_timestamp(factory: sessionmaker[Session]) -> None:
    lead_id, reply_id = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()
    push_customer_followup(factory, reply_id=reply_id, client=client)
    client.remote_records = [
        {
            "record_id": "rec-customer",
            "updated_time": 1784084400000,
            "fields": {"客户唯一键": "xhs:user-1", "当前客户状态": "沟通中", "下次跟进时间": 1784080800000},
        }
    ]

    pull_customer_followup_edits(factory, client=client)

    with factory() as session:
        assert session.get(Lead, lead_id).next_followup_at.isoformat().startswith("2026-07-15T02:00:00")
        mapping = session.scalar(select(FeishuBitableRecord))
        assert mapping.last_remote_updated_at.isoformat().startswith("2026-07-15T03:00:00")


@pytest.mark.parametrize("human_status", ["已收到私信", "沟通中", "已成交", "已忽略"])
def test_push_never_regresses_terminal_human_status(factory: sessionmaker[Session], human_status: str) -> None:
    lead_id, reply_id = _seed_customer(factory, reply_status="sent", followup_status=human_status)
    client = FakeBitableClient()

    push_customer_followup(factory, reply_id=reply_id, client=client)

    assert client.upserts[0][1]["当前客户状态"] == human_status
    with factory() as session:
        assert session.get(Lead, lead_id).followup_status == human_status


def test_push_failure_is_recorded_without_mutating_reply(factory: sessionmaker[Session]) -> None:
    _, reply_id = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()
    client.error = RuntimeError("base unavailable")

    result = push_customer_followup(factory, reply_id=reply_id, client=client)

    assert result.status == "failed"
    with factory() as session:
        reply = session.get(LeadCommentReply, reply_id)
        mapping = session.scalar(select(FeishuBitableRecord))
        assert reply is not None and mapping is not None
        assert reply.status == "sent"
        assert mapping.last_sync_status == "failed"
        assert mapping.last_error == "base unavailable"


def test_pull_isolates_malformed_record_and_commits_valid_record(factory: sessionmaker[Session]) -> None:
    lead_id, _ = _seed_customer(factory, reply_status="sent")
    client = FakeBitableClient()
    client.remote_records = [
        {"record_id": "bad", "fields": {"客户唯一键": "xhs:user-1", "当前客户状态": "沟通中", "下次跟进时间": "not-a-date"}},
        {"record_id": "good", "fields": {"客户唯一键": "xhs:user-1", "当前客户状态": "已成交", "负责人": "小李"}},
    ]

    result = pull_customer_followup_edits(factory, client=client)

    assert result.status == "partial"
    assert result.synced == 1
    assert result.failed == 1
    assert result.errors
    with factory() as session:
        lead = session.get(Lead, lead_id)
        assert lead.followup_status == "已成交"
        assert lead.owner_name == "小李"


@pytest.mark.parametrize("remote_status", ["评论待审核", "评论发送中", "已评论引导，等待客户私信", "评论发送失败", "评论结果待确认"])
def test_pull_rejects_automatic_status_and_preserves_terminal_state(factory: sessionmaker[Session], remote_status: str) -> None:
    lead_id, _ = _seed_customer(factory, reply_status="sent", followup_status="已成交")
    client = FakeBitableClient()
    client.remote_records = [{"record_id": "rec", "fields": {"客户唯一键": "xhs:user-1", "当前客户状态": remote_status}}]

    result = pull_customer_followup_edits(factory, client=client)

    assert result.failed == 1
    with factory() as session:
        assert session.get(Lead, lead_id).followup_status == "已成交"


@pytest.mark.parametrize(
    ("reply_status", "expected"),
    [
        ("pending_review", "评论待审核"),
        ("sending", "评论发送中"),
        ("sent", "已评论引导，等待客户私信"),
        ("failed", "评论发送失败"),
        ("result_unknown", "评论结果待确认"),
    ],
)
def test_push_uses_exact_automatic_status_mapping(factory: sessionmaker[Session], reply_status: str, expected: str) -> None:
    _, reply_id = _seed_customer(factory, reply_status=reply_status)
    client = FakeBitableClient()

    push_customer_followup(factory, reply_id=reply_id, client=client)

    assert client.upserts[0][1]["当前客户状态"] == expected


def test_openapi_list_records_follows_page_tokens() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("page_token") is None:
            return httpx.Response(200, json={"code": 0, "data": {"items": [{"record_id": "rec-1"}], "has_more": True, "page_token": "next"}})
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"record_id": "rec-2"}], "has_more": False}})

    client = _openapi_client(httpx.MockTransport(handler))
    client._tenant_token = "token"

    assert [record["record_id"] for record in client.list_records()] == ["rec-1", "rec-2"]
    assert requests[1].url.params["page_token"] == "next"


def test_openapi_exact_field_search_uses_search_endpoint_and_exact_filter() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "data": {"items": [{"record_id": "rec-1", "fields": {"客户唯一键": "xhs:user-1"}}]}})

    client = _openapi_client(httpx.MockTransport(handler))
    client._tenant_token = "token"

    records = client.find_records_by_exact_field("客户唯一键", "xhs:user-1")

    assert records[0]["record_id"] == "rec-1"
    assert requests[0].url.path.endswith("/records/search")
    assert json.loads(requests[0].content)["filter"]["conditions"][0] == {
        "field_name": "客户唯一键",
        "operator": "is",
        "value": ["xhs:user-1"],
    }


def test_lark_cli_list_records_uses_offset_until_short_page() -> None:
    calls: list[list[str]] = []

    def runner(args: list[str], _: str | None) -> str:
        calls.append(args)
        offset = int(args[args.index("--offset") + 1]) if "--offset" in args else 0
        records = [{"record_id": f"rec-{offset + index}", "fields": {}} for index in range(2 if offset == 0 else 1)]
        return json.dumps({"ok": True, "data": {"records": records}})

    client = FeishuBitableClient(settings=_client_settings(transport="lark_cli", page_size=2), command_runner=runner)

    assert len(client.list_records()) == 3
    assert "--offset" not in calls[0]
    assert calls[1][calls[1].index("--offset") + 1] == "2"


def _openapi_client(transport: httpx.BaseTransport) -> FeishuBitableClient:
    return FeishuBitableClient(settings=_client_settings(), http_client=httpx.Client(transport=transport))


def _client_settings(*, transport: str = "openapi", page_size: int = 100) -> FeishuBitableSettings:
    return FeishuBitableSettings(
        enabled=True,
        app_id="app-id",
        app_secret="app-secret",
        app_token="followup-app",
        table_id="followup-table",
        transport=transport,
        page_size=page_size,
    )


def _seed_customer(
    factory: sessionmaker[Session],
    *,
    reply_status: str,
    lead_status: str = "new",
    followup_status: str | None = None,
) -> tuple[int, int]:
    with factory() as session:
        profile = PublicProfile(platform="xhs", platform_user_id="user-1", display_name="家长")
        session.add(profile)
        session.flush()
        content = Content(
            platform="xhs",
            platform_content_id="note-1",
            content_type="note",
            author_profile_id=profile.id,
            url="https://www.xiaohongshu.com/explore/note-1",
        )
        lead = Lead(
            platform="xhs",
            public_profile_id=profile.id,
            status=lead_status,
            followup_status=followup_status,
        )
        session.add_all([content, lead])
        session.flush()
        comment = Comment(
            platform="xhs",
            platform_comment_id="comment-1",
            content_id=content.id,
            author_profile_id=profile.id,
            body_text="孩子备考 PET 应该怎么规划？",
        )
        session.add(comment)
        session.flush()
        screening = LeadScreeningResult(
            platform="xhs",
            source_entity_type="comment",
            source_entity_id=comment.id,
            content_id=content.id,
            comment_id=comment.id,
            public_profile_id=profile.id,
            demand_type="PET备考",
            human_review_status="valid",
        )
        session.add(screening)
        session.flush()
        reply = LeadCommentReply(
            screening_result_id=screening.id,
            lead_id=lead.id,
            target_comment_id=comment.id,
            target_platform_comment_id=comment.platform_comment_id,
            target_content_id=content.id,
            target_platform_content_id=content.platform_content_id,
            target_url=content.url,
            draft_text="可以先做一次能力诊断。",
            approved_text="可以先做一次能力诊断。",
            status=reply_status,
            sent_at=datetime(2026, 7, 12, 9, 30, tzinfo=UTC) if reply_status == "sent" else None,
            platform_reply_id="reply-1" if reply_status == "sent" else None,
            last_error=None,
        )
        session.add(reply)
        session.commit()
        return lead.id, reply.id
