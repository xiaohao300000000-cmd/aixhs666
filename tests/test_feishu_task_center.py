from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.feishu_task_center import apply_task_center_callback, build_skill_result_card, build_task_catalog_card, build_skill_run_card, build_task_form_card, is_task_center_callback
from storage.database import Base
from storage.models import SkillRun


def test_catalog_and_terminal_cards_render_required_actions() -> None:
    catalog = build_task_catalog_card()
    assert "创建任务" in str(catalog)
    create_button = catalog["body"]["elements"][-1]
    assert create_button["behaviors"] == [{"type": "callback", "value": {"action": "skill_create_screen_historical_leads"}}]
    form = build_task_form_card(SkillRun(id=3, skill_key="screen_historical_leads", skill_version=1, status="draft"))
    submit = form["body"]["elements"][-1]["elements"][-1]
    assert submit["form_action_type"] == "submit"
    assert submit["behaviors"] == [{"type": "callback", "value": {"action": "skill_preview_3"}}]
    failed = SkillRun(id=1, skill_key="screen_historical_leads", skill_version=1, status="failed", error_message="boom")
    assert "重试" in str(build_skill_run_card(failed))
    done = SkillRun(
        id=2,
        skill_key="screen_historical_leads",
        skill_version=1,
        status="succeeded",
        result_summary_json={"processed_count": 3, "raw": "technical-only"},
        business_report_json={
            "conclusion": "本次分析 3 条公开内容，得到 2 个待审核候选。",
            "counts": {
                "priority_review": 1,
                "standard_review": 1,
                "uncertain_review": 0,
                "automatic_exclusion": 0,
            },
            "queue": {"prepared": 2, "quality_control": 0, "emergency": 0},
            "destinations": {"base": {"status": "synced", "detail": "已同步"}},
            "next_action": {"label": "审核本次候选"},
        },
    )
    rendered = str(build_skill_run_card(done))
    assert "本次分析 3 条公开内容" in rendered
    assert "今日审核队列：2" in rendered
    assert "审核本次候选" in rendered
    assert "technical-only" not in rendered
    assert "复制任务" in rendered


def test_task_center_recognizes_real_card_v2_action_value_shape() -> None:
    payload = {"event": {"action": {"value": {"action": "skill_create_screen_historical_leads"}}}}

    assert is_task_center_callback(payload) is True


def test_task_form_selects_use_card_v2_placeholder_instead_of_label() -> None:
    form = build_task_form_card(SkillRun(id=8, skill_key="screen_historical_leads", skill_version=1, status="draft"))
    elements = form["body"]["elements"][-1]["elements"]
    selects = [element for element in elements if element["tag"] == "select_static"]

    assert len(selects) == 3
    assert all("label" not in element for element in selects)
    assert [element["placeholder"]["content"] for element in selects] == ["数据范围", "数据类型", "Campaign"]


def test_result_card_is_distinct_and_links_to_synced_base(monkeypatch) -> None:
    monkeypatch.setenv("FEISHU_BITABLE_APP_TOKEN", "base-token")
    run = SkillRun(
        id=8,
        skill_key="screen_historical_leads",
        skill_version=1,
        status="succeeded",
        parameters_json={"campaign_id": "education_fuzhou_offline", "limit": 50},
        result_summary_json={
            "processed_count": 50,
            "valid_demands": 4,
            "high_intent_customers": 2,
            "needs_confirmation": 7,
            "feishu_sync": {"created": 9, "updated": 3, "failed": 0, "dry_run": 0},
        },
        business_report_json={
            "conclusion": "本次分析 50 条公开内容，得到 12 个待审核候选。",
            "counts": {
                "priority_review": 4,
                "standard_review": 6,
                "uncertain_review": 2,
                "automatic_exclusion": 3,
            },
            "queue": {"prepared": 50, "quality_control": 5, "emergency": 0},
            "destinations": {"base": {"status": "synced", "detail": "已完成 Base 投影"}},
            "next_action": {"label": "审核本次候选"},
        },
    )

    rendered = str(build_skill_result_card(run))

    assert "任务结果详情" in rendered
    assert "本次分析 50 条公开内容" in rendered
    assert "高优先级：4" in rendered
    assert "今日审核队列：50" in rendered
    assert "下一步：审核本次候选" in rendered
    assert "已写入多维表格" in rendered
    assert "tblAHiwa7ip0IkxQ" in rendered
    assert "tblWuVvYREtAPHGs" in rendered


def test_result_card_explicitly_reports_dry_run_as_not_synced() -> None:
    run = SkillRun(
        id=8,
        skill_key="screen_historical_leads",
        skill_version=1,
        status="succeeded",
        result_summary_json={
            "processed_count": 50,
            "valid_demands": 0,
            "high_intent_customers": 0,
            "needs_confirmation": 50,
            "feishu_sync": {"created": 0, "updated": 0, "failed": 0, "dry_run": 100},
        },
    )

    rendered = str(build_skill_result_card(run))

    assert "未写入多维表格" in rendered
    assert "预演 100 条写入" in rendered


def test_result_action_returns_result_detail_card() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(SkillRun(id=8, skill_key="screen_historical_leads", skill_version=1, status="succeeded", result_summary_json={"feishu_sync": {"created": 100, "updated": 0, "failed": 0, "dry_run": 0}}))
        session.commit()

        response = apply_task_center_callback(
            session,
            {"header": {"event_id": "result-8"}, "event": {"action": {"value": {"action": "skill_result_8"}}}},
            verification_token=None,
        )

    assert response["accepted"] is True
    assert response["card"]["header"]["title"]["content"] == "任务结果详情"
