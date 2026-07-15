from services.feishu_skill_run_sync import skill_run_history_fields
from storage.models import SkillRun


def test_skill_run_history_fields_include_operational_summary() -> None:
    run = SkillRun(id=7, skill_key="screen_historical_leads", skill_version=1, status="succeeded", current_stage="summarize", progress_percent=100, requested_by="ou_1", parameters_json={"campaign_id": "campaign"}, result_summary_json={"processed_count": 5, "valid_demands": 3, "high_intent_customers": 2, "needs_confirmation": 1})
    fields = skill_run_history_fields(run)
    assert fields["任务运行ID"] == "7"
    assert fields["处理数量"] == 5
    assert fields["高意向客户"] == 2
