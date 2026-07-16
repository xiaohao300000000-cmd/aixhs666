from services.feishu_skill_run_sync import skill_run_history_fields
from storage.models import SkillRun


def test_skill_run_history_fields_include_operational_summary() -> None:
    run = SkillRun(
        id=7,
        skill_key="screen_historical_leads",
        skill_version=1,
        status="succeeded",
        current_stage="summarize",
        progress_percent=100,
        requested_by="ou_1",
        parameters_json={"campaign_id": "campaign"},
        result_summary_json={"processed_count": 5, "raw": "technical-only"},
        business_report_json={
            "conclusion": "本次得到 4 个待审核候选",
            "counts": {
                "priority_review": 2,
                "standard_review": 1,
                "uncertain_review": 1,
                "automatic_exclusion": 1,
            },
            "queue": {"prepared": 4, "quality_control": 1, "emergency": 0},
            "next_action": {"label": "审核本次候选"},
        },
    )
    fields = skill_run_history_fields(run)
    assert fields["任务运行ID"] == "7"
    assert fields["处理数量"] == 5
    assert fields["业务结论"] == "本次得到 4 个待审核候选"
    assert fields["高优先级候选"] == 2
    assert fields["今日队列"] == 4
    assert fields["下一步"] == "审核本次候选"
    assert "technical-only" not in str(fields)
