# 数据模型

## 1. 设计原则

- 内容本体与发现路径分离
- 同一内容只存一份
- 同一内容可以被多个查询发现
- 原始数据、标准化数据和增强数据分层
- 所有关键数据可以追溯到来源
- 同一公开账号的相关表达可以组成需求事件链

## 2. 核心实体

### queries

```text
id
query_text
platform
query_type
status
priority
source
semantic_cluster_id
run_count
last_run_at
next_run_at
created_at
updated_at
```

`query_type`：

- seed
- generated
- event
- region
- institution
- problem
- control
- exclusion

### contents

```text
id
platform
platform_content_id
content_type
author_profile_id
title
body_text
published_at
url
region_text
like_count
comment_count
collect_count
first_seen_at
last_seen_at
created_at
updated_at
```

唯一键：

```text
platform + platform_content_id
```

### comments

```text
id
platform
platform_comment_id
content_id
parent_comment_id
author_profile_id
body_text
published_at
like_count
reply_count
first_seen_at
last_seen_at
created_at
updated_at
```

唯一键：

```text
platform + platform_comment_id
```

### public_profiles

```text
id
platform
platform_user_id
display_name
profile_url
bio
region_text
public_contact_text
first_seen_at
last_seen_at
created_at
updated_at
```

### discovery_relations

记录数据如何被发现。

```text
id
query_id
content_id
rank_position
result_page
discovery_method
discovered_at
```

### collection_tasks

```text
id
task_type
platform
target_id
query_id
priority
status
attempt_count
max_attempts
scheduled_at
started_at
finished_at
last_error
worker_id
cursor_json
payload_json
created_at
updated_at
```

状态：

- pending
- running
- completed
- partial
- retry
- blocked
- failed
- cancelled

### snapshots

```text
id
entity_type
entity_id
snapshot_type
object_storage_path
content_hash
captured_at
```

`snapshot_type`：

- raw_json
- html
- screenshot
- text
- metadata

### collection_events

```text
id
event_type
entity_type
entity_id
event_data
occurred_at
```

事件示例：

- content_first_seen
- content_updated
- new_comment_found
- profile_updated
- query_hit
- comment_count_changed
- task_failed

### semantic_clusters

```text
id
name
description
representative_examples
status
created_at
updated_at
```

### phrase_candidates

```text
id
phrase
source_text_count
semantic_cluster_id
novelty_score
query_potential_score
status
created_at
reviewed_at
```

状态：

- pending
- approved
- rejected
- converted_to_query

### institutions

```text
id
name
aliases
region_text
institution_type
created_at
updated_at
```

### entity_mentions

```text
id
source_entity_type
source_entity_id
target_entity_type
target_entity_id
mention_text
confidence
created_at
```

### demand_events

用于组成需求事件链。

```text
id
profile_id
source_entity_type
source_entity_id
event_type
event_time
signal_strength
freshness_class
evidence_text
created_at
```

`event_type` 示例：

- exam_failed
- planning_question
- institution_comparison
- price_question
- dissatisfaction
- local_search
- trial_request
- schedule_question

`freshness_class`：

- realtime
- near_term
- long_term
- intelligence_only

### human_feedback

```text
id
target_type
target_id
reviewer
feedback_type
label
notes
created_at
```

用于记录：

- 保留
- 忽略
- 软广
- 真实需求
- 标签错误
- 预警有效
- 预警无效

### leads

面向 AI 自动获客的潜在客户对象，按公开平台用户聚合。

```text
id
platform
public_profile_id
status
region_text
demand_type
product
intent_stage
intent_score
information_completeness
known_info_json
missing_info_json
recommended_next_step
first_seen_at
last_seen_at
created_at
updated_at
```

唯一键：

```text
platform + public_profile_id
```

`status`：

- new
- needs_enrichment
- qualified
- handled
- ignored

### lead_evidence

保存潜在客户判断依据。每条证据必须追溯到帖子或评论。

```text
id
lead_id
source_entity_type
source_entity_id
content_id
comment_id
evidence_text
demand_type
intent_stage
score_contribution
created_at
```

唯一键：

```text
lead_id + source_entity_type + source_entity_id
```

### enrichment_tasks

保存待完善信息和后续动作。

```text
id
lead_id
task_type
status
reason
created_at
updated_at
```

唯一键：

```text
lead_id + task_type
```

## 3. 三层数据

### Raw 层

保存平台原始返回或页面快照。

### Normalized 层

统一平台字段、时间、ID 和关系。

### Enriched 层

保存：

- 语义簇
- 地域识别
- 年级识别
- 考试识别
- 意图假设
- 情绪和急迫度
- 黑话映射
- 人工标签
- 高价值信号
- 需求事件链

## 4. 去重策略

### ID 去重

优先使用平台内容 ID 和评论 ID。

### 文本哈希去重

处理重复搬运和平台 ID 变化。

### 语义相似去重

识别轻微改写，但不删除不同来源版本。

## 5. 索引建议

- queries(status, next_run_at)
- contents(platform, platform_content_id)
- comments(platform, platform_comment_id)
- comments(content_id, published_at)
- discovery_relations(query_id, discovered_at)
- collection_tasks(status, scheduled_at, priority)
- demand_events(profile_id, event_time)
- phrase_candidates(status, novelty_score)
