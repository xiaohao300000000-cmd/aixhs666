# Qualification Architecture Audit

Date: 2026-07-07

Scope: current lead qualification, LLM screening, Feishu review, workbench sync, query/source scoring, text extraction, and location/IP evidence flow.

## Summary

The current lead system is still a working education-specific implementation. It can screen real Xiaohongshu comments through DeepSeek and Feishu review, but the definition of "worth following up" is spread across rule filters, LLM prompt text, lead generation, source scoring, Feishu presentation, and query helpers.

The minimum safe migration is to add a Campaign and Qualification Policy layer without moving the whole business domain into a plugin system. This task should migrate only the generic qualification decision and location policy surface. Domain terms such as KET/PET and education copy can remain in the default education campaign/domain pack for now.

## Hard-Coded Business Assumptions

| File/function | Current hard-coded content | Should belong to | Modification risk | Migrate in this task |
| --- | --- | --- | --- | --- |
| `services/lead_intent.py` `TARGET_PRODUCTS` | `KET`, `PET`, `小剑桥` define in-scope products. | Domain Pack | Medium: existing lead tests depend on this. | No; document as education domain defaults. |
| `services/lead_intent.py` `OUT_OF_SCOPE_WORDS` | `雅思`, `托福`, `PTE`, `考研`, `成人英语`, `四六级` are rejected unless KET/PET is present. | Domain Pack / Campaign | Medium: this blocks nationwide IELTS campaigns if reused. | No direct change; default qualification layer must not reuse this list for non-education campaigns. |
| `services/lead_intent.py` `ACTION_PATTERNS` | Price, trial, institution, course, retry, comparison, improvement terms are education-course terms. | Domain Pack | Medium: workbench and lead generation depend on these labels. | No. |
| `services/lead_intent.py` `classify_lead_intent` | High confidence boosted by `孩子`, `娃`, grades, and `福州`. | Qualification Policy / Location Policy / Domain Pack | High: changes lead scoring. | Partially: new qualification policy owns score threshold and location policy; old classifier remains for compatibility. |
| `services/lead_intent.py` `_missing_info` | Missing info fixed to `地区`, `年级`, `考试时间`; region examples fixed to `福州`, `厦门`, `上海`, `北京`, `线上`, `线下`. | Qualification Policy / Domain Pack | Medium. | Partially through new policy outputs; old copy unchanged. |
| `services/lead_intent.py` `_human_need`, `_next_step`, `_action_label` | Human-readable copy assumes parents, children, English institutions, course price, and exams. | Domain Pack / Outreach Policy | Low for backend, high for user-facing copy. | No. |
| `services/llm_lead_screening.py` `OpenAICompatibleLeadScreeningClient.screen` | System prompt says "教育获客线索筛选助手" and asks for education lead decision. | Domain Pack / Campaign | High: changing prompt changes production LLM behavior. | No; this task must not call or retune DeepSeek. |
| `services/llm_lead_screening.py` `JUNK_TEXTS`, `SPAM_WORDS` | Filter terms include education-resource spam such as `资料包`, `求资料`, `私信领取`. | Domain Pack / Qualification Policy | Medium. | No. |
| `services/llm_lead_screening.py` `REGION_KEYWORDS` | City list fixed to 福州/厦门/泉州/上海/北京/广州/深圳/杭州/南京/苏州. | Location Policy / Platform Adapter | Medium: affects lead region extraction. | Yes for new qualification engine; old extraction remains. |
| `services/llm_lead_screening.py` `PRODUCT_KEYWORDS` | Product detection fixed to KET/PET and 小五/小六. | Domain Pack | Medium. | No. |
| `services/llm_lead_screening.py` thresholds | `REVIEW_CONFIDENCE_THRESHOLD=0.65`, `HIGH_CONFIDENCE_THRESHOLD=0.75`. | Qualification Policy | Medium: review and lead status depend on them. | Yes: new qualification policy has `minimum_intent_score`; old thresholds remain for compatibility. |
| `services/llm_lead_screening.py` `_review_status` | `review_required` or low confidence becomes `needs_review`, otherwise valuable maps to accepted/rejected. | Qualification Policy | Medium. | Yes for new qualification result; no change to existing review status. |
| `services/llm_lead_screening.py` `_lead_status` | Needs review, high confidence, and high intent map to `needs_review`, `qualified`, or `needs_enrichment`. | Qualification Policy / Outreach Policy | Medium. | No direct mutation; new qualification result is stored separately. |
| `services/lead_generation.py` `PRODUCT_KEYWORDS` | KET/PET product extraction. | Domain Pack | Medium. | No. |
| `services/lead_generation.py` `REGION_KEYWORDS` | City extraction list is fixed and text-derived. | Location Policy | Medium. | Yes for new qualification engine. |
| `services/lead_generation.py` `_has_lead_intent` | Strong content and comment terms fixed to education demand words. | Domain Pack / Qualification Policy | High: changes lead generation. | No. |
| `services/lead_generation.py` `_score_record` | Fixed scores for demand events and boosts for `求推荐`, `哪家`, `机构`, `冲刺班`, `试听`, `价格`, `多少钱`. | Qualification Policy / Domain Pack | High. | Partially: new policy uses configurable minimum score; old scoring remains. |
| `services/lead_generation.py` `_automatic_status` | `intent_score >= 80` and `information_completeness >= 80` means `qualified`. | Qualification Policy | Medium. | Yes in new qualification output only. |
| `services/lead_generation.py` `_recommended_next_step`, `_missing_reason` | Follow-up copy assumes public contact, region service range, and course/product. | Outreach Policy | Low. | No. |
| `services/feishu_ai_workbench.py` constants | Raw intent words, out-of-scope words, customer-content words all education-specific. | Domain Pack | Medium. | No. |
| `services/feishu_ai_workbench.py` output fields | Fields such as `课程/考试`, `需求摘要`, `AI判断`, `动作`, `为什么推荐` are fixed for education workbench. | Outreach Policy | Low. | No. |
| `services/feishu_workbench.py` `build_workbench_fields` | Feishu Base columns are fixed: `客户`, `需求`, `课程/考试`, `意向程度`, `为什么推荐`, `下一步`, `状态`. | Outreach Policy | Low. | No. |
| `integrations/feishu/llm_review.py` `build_llm_review_card` | Card title and markdown copy say "LLM 客户线索审核", `原文`, `上下文摘要`, `证据`, `AI说明`. | Outreach Policy | Low. | No. |
| `apps/worker/source_pool.py` `HIGH_VALUE_KEYWORDS` | High value sources use `福州`, `厦门`, `机构`, `课程`, `价格`, `试听`, `KET`, `PET`. | Campaign / Domain Pack / Source Strategy | Medium. | No. |
| `intelligence/text_processing/processor.py` `_REGION_TERMS` | Region extraction has a fixed city list. | Location Policy / Platform Adapter | Medium. | Yes for new qualification engine; existing extractor remains. |
| `intelligence/text_processing/processor.py` `_EXAM_TERMS`, institutions, suffixes | Exams and institution brands/suffixes assume education. | Domain Pack | Low to medium. | No. |
| `intelligence/demand_chain/chain.py` `_TYPE_KEYWORDS` | Demand types are generic-ish but heavily course/service oriented: price, trial, comparison, exam retry, planning. | Core Engine / Domain Pack boundary | Medium. | No. |
| `intelligence/phrase_discovery/discovery.py` `_HIGH_INTENT_TERMS` | Phrase scoring boosts education/service terms: `试听`, `价格`, `二刷`, `压线`, `冲刺`, etc. | Domain Pack / Query Strategy | Low. | No. |
| `intelligence/content_insights/insights.py` `_QUESTION_TERMS`, `_ACTION_TERMS` | Content insight action terms are education/service terms. | Domain Pack | Low. | No. |
| `storage.models.Lead` fields | `demand_type`, `product`, `intent_stage`, `intent_score`, `information_completeness` are generic enough, but current values are education-derived. | Core Engine | Low. | Reuse. |
| `storage.models.LeadScreeningResult` fields | LLM result stores review status, evidence, confidence, reason, and workflow status, but has no qualification-policy result fields. | Core Engine / Qualification Policy | Medium. | Yes: add separate qualification result fields if persisting decisions. |

## Current Location/IP Evidence Flow

| Source | Current state | Conclusion |
| --- | --- | --- |
| `PublicProfile.region_text` | Model exists and ingest maps `CollectedProfile.region_text`, but live DB has 0/641 non-empty values. | Reuse if populated; current history has no profile location evidence. |
| `Content.region_text` | Model exists and ingest maps `CollectedContent.region_text`, but live DB has 0/163 non-empty values. | Reuse if populated; current history has no content location evidence. |
| `Comment.region_text` | `CollectedComment` has `region_text`, but `storage.models.Comment` has no column and ingest drops it. | Not persisted today. |
| Playwright Xiaohongshu parser | Parses `ip_location`, `ipLocation`, `location`, `region` into profile/content/comment `region_text`; fixtures contain 福建 and 福州. | Platform adapter can expose IP/location evidence. |
| MediaCrawler adapter | Main production adapter sets content/comment/profile `region_text=None`. | Main production path does not preserve location/IP. |
| Third-party MediaCrawler code | `tools/user_hash.py` and `database/models.py` explicitly state user ID, IP location, avatar, profile link, signature, and gender are not collected/persisted. | Historical MediaCrawler JSONL cannot be assumed to contain IP location. |
| `.runtime/storage-snapshots` | Existing snapshots show `region_text:null` in sampled search/content/comment responses. | Existing snapshots do not provide usable IP evidence. |
| Text body/title/comment | Contains possible city terms, but text mention is weaker than platform IP location. | Use as `content_text` / `comment_text` location evidence with lower confidence. |

Live DB check on 2026-07-07:

```text
public_profiles_total=641
public_profiles_region_nonnull=0
contents_total=163
contents_region_nonnull=0
comments_total=516
comments_has_region_column=false
snapshots_total=364
```

## Classification

### Core Engine

- Lead and screening persistence.
- Workflow states.
- Generic qualification output structure: decision, reason codes, confidence, evidence IDs, policy version.
- Generic location evidence and location match status.

### Campaign

- Campaign ID, enabled flag, platforms, service mode, source strategy, domain ID, and policy version.
- Which domain pack and policy to use by default.

### Domain Pack

- KET/PET, 雅思, 托福, education institutions, parents/children, grade/exam terms.
- Demand keywords, product extraction, and business labels.

### Qualification Policy

- Minimum intent score.
- Maximum signal age.
- Allowed/excluded personas.
- Manual review conditions.
- Decision mapping and reason codes.

### Location Policy

- Required vs not required.
- Target countries/provinces/cities.
- Nearby regions.
- Unknown/conflict/non-match actions.
- Nationwide and overseas rules.

### Platform Adapter

- Whether platform exposes IP location.
- Original raw IP/location value.
- Mapping granularity: province vs city.

### Outreach Policy

- Feishu card copy.
- Feishu Base column names.
- Next-step copy and status labels.

## Recommended Minimal Migration

1. Add Pydantic configuration models for Campaign, Qualification Policy, Location Policy, Location Evidence, and Qualification Result.
2. Add JSON campaign configs for current education/Fuzhou offline, nationwide online IELTS, and Xiamen automotive local.
3. Add a read-only qualification engine that consumes existing `LeadScreeningResult` rows and evidence text without calling DeepSeek or sending Feishu cards.
4. Persist qualification result on `lead_screening_results` only if a migration is added; keep it separate from existing `review_status` and workflow status.
5. Treat missing historical IP/location evidence as `unknown`, never as `not_matched`.
6. Keep existing education LLM prompt and old rule classifiers unchanged to avoid production behavior regression.
