from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from intelligence.text_processing import normalize_text


class LeadEntryType(str, Enum):
    PUSH = "push"
    CONFIRM = "confirm"
    SKIP = "skip"


class LeadIntentAction(str, Enum):
    COURSE = "course"
    INSTITUTION = "institution"
    PRICE = "price"
    TRIAL = "trial"
    ENROLLMENT = "enrollment"
    EXAM_RETRY = "exam_retry"
    COMPARISON = "comparison"
    IMPROVEMENT = "improvement"


class LeadSkipReason(str, Enum):
    AD = "ad"
    PROVIDER = "provider"
    GUIDE = "guide"
    RESOURCE_REQUEST = "resource_request"
    NO_CLEAR_NEED = "no_clear_need"
    OUT_OF_SCOPE = "out_of_scope"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LeadIntentDecision:
    entry_type: LeadEntryType
    actions: tuple[LeadIntentAction, ...] = ()
    confidence: str = "low"
    human_need: str = ""
    recommendation_reason: str = ""
    suggested_next_step: str = ""
    missing_info: tuple[str, ...] = ()
    skip_reason: LeadSkipReason | None = None


TARGET_PRODUCTS = ("KET", "PET", "ket", "pet", "小剑桥")
RESOURCE_WORDS = ("求资料", "求分享", "蹲资料", "发我一份", "领取资料", "资料包", "真题资料", "分享吗")
PROVIDER_WORDS = (
    "招生",
    "欢迎咨询",
    "课程顾问",
    "老师带",
    "教了",
    "私信我",
    "报名入口",
    "机构问我",
    "能不能教",
    "教学大纲",
    "小班教学",
)
GUIDE_WORDS = ("攻略", "汇总", "总结", "干货", "备考规划", "避坑指南", "真题", "整理", "扣分点")
OUT_OF_SCOPE_WORDS = ("雅思", "托福", "PTE", "考研", "成人英语", "四六级")
PROMO_WORDS = ("专业机构", "靠谱机构", "同团队", "系统规划", "稳步规划", "机构帮孩子")
NO_NEED_WORDS = ("没有报班", "没报英文班", "不为考试", "不为考级", "无所谓", "节约钱和时间")
ACTION_PATTERNS: tuple[tuple[LeadIntentAction, tuple[str, ...]], ...] = (
    (LeadIntentAction.PRICE, ("多少钱", "价格", "费用", "收费", "课时费")),
    (LeadIntentAction.TRIAL, ("试听", "体验课")),
    (LeadIntentAction.ENROLLMENT, ("报班", "报名", "要不要报", "需要报")),
    (LeadIntentAction.INSTITUTION, ("推荐机构", "机构推荐", "哪家机构", "线下机构", "线上机构", "推荐吗", "求推荐")),
    (LeadIntentAction.COURSE, ("线上带", "线下课", "冲刺班", "课程", "一对一")),
    (LeadIntentAction.EXAM_RETRY, ("没过", "压线", "二刷", "重考", "再考")),
    (LeadIntentAction.COMPARISON, ("哪个好", "怎么选", "纠结", "对比")),
    (LeadIntentAction.IMPROVEMENT, ("怎么提高", "怎么提升", "阅读弱", "听力弱", "写作弱", "跟不上")),
)


def classify_lead_intent(text: str, *, source_entity_type: str, context_text: str = "") -> LeadIntentDecision:
    raw = " ".join(part for part in (context_text, text) if part)
    normalized = normalize_text(raw)
    normalized_text = normalize_text(text)
    if not _contains_any(normalized, TARGET_PRODUCTS):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.OUT_OF_SCOPE)
    if _contains_any(normalized, OUT_OF_SCOPE_WORDS) and not _contains_any(normalized, ("KET", "PET", "ket", "pet")):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.OUT_OF_SCOPE)
    if _contains_any(normalized_text, RESOURCE_WORDS):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.RESOURCE_REQUEST)
    if source_entity_type == "content" and _contains_any(normalized_text, PROVIDER_WORDS):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.PROVIDER)
    if source_entity_type == "content" and _contains_any(normalized_text, GUIDE_WORDS) and (
        not _contains_question(normalized_text) or _looks_rhetorical_content(normalized_text)
    ):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.GUIDE)
    if source_entity_type == "comment" and _contains_any(normalized_text, PROMO_WORDS):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.AD)
    if source_entity_type == "comment" and _contains_any(normalized_text, NO_NEED_WORDS):
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.NO_CLEAR_NEED)

    actions = _detect_actions(normalized)
    if not actions:
        return LeadIntentDecision(entry_type=LeadEntryType.SKIP, skip_reason=LeadSkipReason.NO_CLEAR_NEED)

    confidence = "high" if len(actions) >= 2 or _contains_any(normalized, ("孩子", "娃", "五年级", "四年级", "福州")) else "medium"
    entry_type = LeadEntryType.PUSH if confidence == "high" else LeadEntryType.CONFIRM
    missing = _missing_info(normalized)
    return LeadIntentDecision(
        entry_type=entry_type,
        actions=actions,
        confidence=confidence,
        human_need=_human_need(actions),
        recommendation_reason=_recommendation_reason(actions, confidence),
        suggested_next_step=_next_step(missing, actions),
        missing_info=missing,
    )


def _detect_actions(normalized: str) -> tuple[LeadIntentAction, ...]:
    actions: list[LeadIntentAction] = []
    for action, words in ACTION_PATTERNS:
        if _contains_any(normalized, words):
            actions.append(action)
    return tuple(actions)


def _missing_info(normalized: str) -> tuple[str, ...]:
    missing: list[str] = []
    if not _contains_any(normalized, ("福州", "厦门", "上海", "北京", "线上", "线下")):
        missing.append("地区")
    if not _contains_any(normalized, ("一年级", "二年级", "三年级", "四年级", "五年级", "六年级", "孩子", "娃")):
        missing.append("年级")
    if not _contains_any(normalized, ("考试", "暑假", "寒假", "本月", "下个月", "二刷")):
        missing.append("考试时间")
    return tuple(missing)


def _human_need(actions: tuple[LeadIntentAction, ...]) -> str:
    if LeadIntentAction.EXAM_RETRY in actions:
        return "孩子考试没过或准备二刷，家长在找提升方案"
    if LeadIntentAction.PRICE in actions:
        return "家长在了解课程价格"
    if LeadIntentAction.INSTITUTION in actions:
        return "家长在找合适的英语机构"
    if LeadIntentAction.IMPROVEMENT in actions:
        return "家长在询问孩子英语提升方法"
    return "家长在咨询KET/PET相关学习安排"


def _recommendation_reason(actions: tuple[LeadIntentAction, ...], confidence: str) -> str:
    action_names = "、".join(action.value for action in actions)
    return f"文本包含明确咨询动作：{action_names}；置信度为{confidence}"


def _next_step(missing: tuple[str, ...], actions: tuple[LeadIntentAction, ...]) -> str:
    if missing:
        return f"先确认{missing[0]}，再判断是否适合跟进"
    if LeadIntentAction.PRICE in actions:
        return "可先询问孩子年级和目标考试时间，再给课程建议"
    return "可根据原评论问题做一次轻量人工判断"


def _contains_question(normalized: str) -> bool:
    return "?" in normalized or "？" in normalized or any(word in normalized for word in ("请问", "怎么", "要不要", "有没有"))


def _looks_rhetorical_content(normalized: str) -> bool:
    direct_need_words = ("请问", "求推荐", "求问", "想问", "哪家", "有没有", "怎么选", "多少钱", "价格多少", "试听", "体验课")
    return not _contains_any(normalized, direct_need_words)


def _contains_any(normalized: str, words: tuple[str, ...]) -> bool:
    return any(word in normalized for word in words)
