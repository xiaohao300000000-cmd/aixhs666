from services.lead_intent import LeadEntryType, LeadIntentAction, LeadSkipReason, classify_lead_intent


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


def test_recommendation_reason_is_human_readable_chinese_only() -> None:
    decision = classify_lead_intent("孩子PET没过，福州有二刷冲刺班推荐吗？", source_entity_type="comment")

    assert decision.recommendation_reason
    for token in ("exam_retry", "institution", "course", "high", "medium"):
        assert token not in decision.recommendation_reason
