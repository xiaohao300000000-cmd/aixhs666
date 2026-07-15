from __future__ import annotations

from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from storage.database import Base
from storage.models import SkillRun, SkillRunEvent


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_skill_run_persists_parameters_and_ordered_events() -> None:
    factory = _factory()
    with factory() as session:
        run = SkillRun(
            skill_key="screen_historical_leads",
            skill_version=1,
            status="draft",
            parameters_json={"limit": 50},
            requested_by="ou_operator",
            idempotency_key="create:event-1",
        )
        run.events.extend(
            [
                SkillRunEvent(sequence=1, event_type="created", status="draft"),
                SkillRunEvent(sequence=2, event_type="previewed", status="previewed", data_json={"candidates": 12}),
            ]
        )
        session.add(run)
        session.commit()

        loaded = session.scalar(select(SkillRun).where(SkillRun.id == run.id))

        assert loaded is not None
        assert loaded.parameters_json == {"limit": 50}
        assert [item.event_type for item in loaded.events] == ["created", "previewed"]


def test_skill_run_event_sequence_and_event_key_are_unique() -> None:
    factory = _factory()
    with factory() as session:
        first = SkillRun(skill_key="screen_historical_leads", skill_version=1, status="draft")
        second = SkillRun(skill_key="screen_historical_leads", skill_version=1, status="draft")
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                SkillRunEvent(skill_run_id=first.id, sequence=1, event_type="created", event_key="callback:event-1"),
                SkillRunEvent(skill_run_id=first.id, sequence=1, event_type="duplicate-sequence"),
            ]
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate event sequence must fail")

        session.add_all(
            [
                SkillRunEvent(skill_run_id=first.id, sequence=1, event_type="created", event_key="callback:event-1"),
                SkillRunEvent(skill_run_id=second.id, sequence=1, event_type="created", event_key="callback:event-1"),
            ]
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate callback event key must fail")


def test_deleting_skill_run_cascades_events() -> None:
    factory = _factory()
    with factory() as session:
        run = SkillRun(skill_key="screen_historical_leads", skill_version=1, status="draft")
        run.events.append(SkillRunEvent(sequence=1, event_type="created"))
        session.add(run)
        session.commit()
        event_id = run.events[0].id

        session.delete(run)
        session.commit()

        assert session.get(SkillRunEvent, event_id) is None
