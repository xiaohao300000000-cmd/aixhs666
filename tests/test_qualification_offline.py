from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from scripts.validate_campaign_config import main as validate_config_main
from scripts.validate_qualification_offline import build_qualification_validation_report, main as offline_main
from storage.database import Base
from storage.models import Comment, Content, LeadScreeningResult


def test_validate_campaign_config_command_outputs_summary(capsys) -> None:
    exit_code = validate_config_main(["configs/campaigns/education_fuzhou_offline.json"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["campaign_id"] == "education_fuzhou_offline"
    assert output["domain_id"] == "education"
    assert output["service_mode"] == "offline"
    assert output["location_scope"] == "city:福州"
    assert output["validation_result"] == "passed"


def test_offline_validation_report_compares_campaign_location_behavior(factory: sessionmaker[Session]) -> None:
    _seed_screenings(factory)

    with factory() as session:
        report = build_qualification_validation_report(
            session,
            campaign_paths=[
                "configs/campaigns/education_fuzhou_offline.json",
                "configs/campaigns/ielts_nationwide_online.json",
            ],
        )

    fuzhou = report["campaigns"]["education_fuzhou_offline"]
    nationwide = report["campaigns"]["ielts_nationwide_online"]
    assert fuzhou["total_records"] == 2
    assert fuzhou["location_matched"] == 1
    assert fuzhou["location_unknown"] == 1
    assert fuzhou["needs_review"] == 1
    assert nationwide["location_not_required"] == 2
    assert nationwide["qualified"] == 2
    assert nationwide["needs_review"] == 0
    assert "current_comment" not in json.dumps(report, ensure_ascii=False)


def test_offline_validation_command_writes_non_sensitive_report(factory: sessionmaker[Session], tmp_path: Path, monkeypatch) -> None:
    _seed_screenings(factory)
    output = tmp_path / "qualification-validation-result.json"
    monkeypatch.setattr("scripts.validate_qualification_offline.SessionLocal", factory)

    exit_code = offline_main(
        [
            "--campaign",
            "configs/campaigns/education_fuzhou_offline.json",
            "--campaign",
            "configs/campaigns/ielts_nationwide_online.json",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert set(payload["campaigns"]) == {"education_fuzhou_offline", "ielts_nationwide_online"}
    assert "老师，福州" not in output.read_text(encoding="utf-8")


def test_offline_validation_prefers_structured_comment_region_text(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        content = Content(platform="xhs", platform_content_id="note-1", content_type="note", title="KET", body_text="讨论")
        session.add(content)
        session.flush()
        comment = Comment(
            platform="xhs",
            platform_comment_id="comment-1",
            content_id=content.id,
            body_text="老师，KET 冲刺班多少钱？",
            region_text="福州",
        )
        session.add(comment)
        session.flush()
        session.add(
            LeadScreeningResult(
                platform="xhs",
                source_entity_type="comment",
                source_entity_id=comment.id,
                comment_id=comment.id,
                review_status="accepted",
                workflow_status="llm_done",
                valuable=True,
                confidence=88,
                context_json={"current_comment": "老师，KET 冲刺班多少钱？"},
            )
        )
        session.commit()

    with factory() as session:
        report = build_qualification_validation_report(
            session,
            campaign_paths=["configs/campaigns/education_fuzhou_offline.json"],
        )

    result = report["campaigns"]["education_fuzhou_offline"]
    assert result["location_matched"] == 1
    assert result["ip_only_evidence"] == 1
    assert result["qualified"] == 1


def _seed_screenings(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        session.add_all(
            [
                LeadScreeningResult(
                    platform="xhs",
                    source_entity_type="comment",
                    source_entity_id=1,
                    review_status="accepted",
                    workflow_status="llm_done",
                    valuable=True,
                    confidence=88,
                    context_json={
                        "current_comment": "老师，福州 KET 冲刺班多少钱？",
                        "post_body": "家长交流",
                        "profile_region": "",
                    },
                ),
                LeadScreeningResult(
                    platform="xhs",
                    source_entity_type="comment",
                    source_entity_id=2,
                    review_status="accepted",
                    workflow_status="llm_done",
                    valuable=True,
                    confidence=88,
                    context_json={
                        "current_comment": "老师，KET 冲刺班多少钱？",
                        "post_body": "家长交流",
                        "profile_region": "",
                    },
                ),
            ]
        )
        session.commit()


@pytest.fixture()
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    yield SessionLocal
    Base.metadata.drop_all(engine)
    engine.dispose()
