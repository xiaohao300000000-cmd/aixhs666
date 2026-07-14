from services.feishu_task_center import build_task_catalog_card, build_skill_run_card
from storage.models import SkillRun


def test_catalog_and_terminal_cards_render_required_actions() -> None:
    assert "创建任务" in str(build_task_catalog_card())
    failed = SkillRun(id=1, skill_key="screen_historical_leads", skill_version=1, status="failed", error_message="boom")
    assert "重试" in str(build_skill_run_card(failed))
    done = SkillRun(id=2, skill_key="screen_historical_leads", skill_version=1, status="succeeded", result_summary_json={"processed_count": 3, "valid_demands": 2, "high_intent_customers": 1, "needs_confirmation": 1, "feishu_sync": {"created": 2, "updated": 0, "failed": 0}})
    rendered = str(build_skill_run_card(done))
    assert "高意向客户" in rendered and "复制任务" in rendered
