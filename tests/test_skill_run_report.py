from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from storage.database import Base
from storage.models import SkillRun


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_skill_run_business_report_is_separate_from_raw_summary_and_checkpoint() -> None:
    factory = _factory()
    with factory() as session:
        run = SkillRun(
            skill_key="screen_historical_leads",
            skill_version=1,
            status="succeeded",
            checkpoint_json={"screening_ids": [1, 2]},
            result_summary_json={"processed_count": 2, "legacy_key": "preserved"},
            business_report_json={"conclusion": "发现 2 条候选"},
        )
        session.add(run)
        session.commit()

        stored = session.scalar(select(SkillRun))
        assert stored is not None
        assert stored.business_report_json == {"conclusion": "发现 2 条候选"}
        assert stored.result_summary_json == {"processed_count": 2, "legacy_key": "preserved"}
        assert stored.checkpoint_json == {"screening_ids": [1, 2]}
