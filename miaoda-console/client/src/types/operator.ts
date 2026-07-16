export type AttentionCounts = {
  review_queue: number;
  running_skills: number;
  failed_tasks: number;
  stale_workers: number;
};

export type LeadQueueItem = {
  id: number;
  display_name: string;
  status: string;
  region_text: string | null;
  demand_type: string | null;
  intent_stage: string | null;
  intent_score: number;
  information_completeness: number;
  recommended_next_step: string | null;
  evidence_text: string | null;
  updated_at: string | null;
};

export type SkillRunItem = {
  id: number;
  skill_key: string;
  status: string;
  current_stage: string | null;
  progress_current: number;
  progress_total: number;
  progress_percent: number;
  error_message: string | null;
  updated_at: string | null;
};

export type TaskFailureItem = {
  id: number;
  task_type: string;
  platform: string;
  target_id: string | null;
  attempt_count: number;
  max_attempts: number;
  last_error: string | null;
  finished_at: string | null;
  updated_at: string | null;
};

export type WorkerItem = {
  worker_id: string;
  status: string;
  health: 'healthy' | 'stale';
  current_task_id: number | null;
  completed_task_count: number;
  failed_task_count: number;
  last_error: string | null;
  last_heartbeat_at: string | null;
};

export type NextAction = {
  kind: 'review_leads' | 'inspect_failure' | 'monitor_run' | 'none';
  title: string;
  description: string;
  target: string;
};

export type OperatorWorkbench = {
  generated_at: string;
  attention: AttentionCounts;
  lead_queue: LeadQueueItem[];
  skill_runs: SkillRunItem[];
  task_failures: TaskFailureItem[];
  workers: WorkerItem[];
  next_action: NextAction;
};

export type OperatorErrorReason =
  | 'missing_base_url'
  | 'missing_token'
  | 'backend_unreachable'
  | 'backend_unavailable'
  | 'backend_unauthorized'
  | 'invalid_request'
  | 'resource_not_found'
  | 'state_conflict'
  | 'validation_failed'
  | 'unknown';

export type OperatorLeadEvidence = {
  id: number;
  source_type: string;
  source_id: number;
  text: string;
  demand_type: string | null;
  intent_stage: string | null;
  score: number;
};

export type OperatorLead = {
  id: number;
  display_name: string;
  profile_url: string | null;
  platform: string;
  status: string;
  region_text: string | null;
  demand_type: string | null;
  product: string | null;
  intent_stage: string | null;
  intent_score: number;
  information_completeness: number;
  known_info: Record<string, unknown>;
  missing_info: string[];
  recommended_next_step: string | null;
  owner_name: string | null;
  operator_note: string | null;
  followup_status: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  updated_at: string | null;
  evidence: OperatorLeadEvidence[];
  screening: {
    id: number;
    model_name: string | null;
    valuable: boolean | null;
    intent_strength: string | null;
    confidence: number | null;
    evidence: string[];
    review_status: string;
    status_reason: string | null;
    human_review_status: string | null;
    qualification_decision: string | null;
    reason_codes: string[];
    human_reason: string | null;
    policy_version: string | null;
    source_url: string | null;
  } | null;
};

export type OperatorLeadQueue = {
  total: number;
  pending_total: number;
  items: OperatorLead[];
  filters: string[];
};

export type LeadReviewAction = 'promote' | 'defer' | 'reject';

export type CustomerProgression = {
  customer_id: number;
  customer_stage: 'awaiting_first_contact' | 'deferred' | 'invalid' | string;
  next_action: 'prepare_public_reply' | 'wait_for_reactivation' | 'none' | string;
  timeline_event_id: number;
  timeline_event_type: string;
  screening_id: number | null;
  idempotent_replay: boolean;
};

export type LeadReviewResult = {
  lead: OperatorLead;
  progression: CustomerProgression;
};

export type SkillTemplate = {
  key: string;
  name: string;
  version: number;
  description: string;
  stages: string[];
  external_read: boolean;
  external_write: boolean;
  cancellable: boolean;
  retryable: boolean;
  defaults: SkillRunParameters;
};

export type SkillRunParameters = {
  data_range: 'all' | 'last_30_days' | 'last_90_days';
  source_types: 'content_and_comment' | 'content_only' | 'comment_only';
  limit: number;
  campaign_id: string;
};

export type OperatorSkillRun = {
  id: number;
  skill_key: string;
  skill_version: number;
  status: string;
  stage: string | null;
  progress: { current: number; total: number; percent: number };
  parameters: Partial<SkillRunParameters>;
  preview: Record<string, unknown>;
  result: Record<string, unknown>;
  error: { code: string | null; message: string | null } | null;
  requested_by: string | null;
  retry_count: number;
  copied_from_run_id: number | null;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  events: Array<{
    sequence: number;
    type: string;
    stage: string | null;
    status: string | null;
    message: string | null;
    progress_current: number | null;
    progress_total: number | null;
    data: Record<string, unknown>;
    created_at: string | null;
  }>;
};

export type OperatorTaskCenter = {
  templates: SkillTemplate[];
  campaigns: Array<{ id: string; name: string; service_mode: string; location_summary: string }>;
  runs: OperatorSkillRun[];
};

export type ReviewLayer =
  | 'priority_review'
  | 'standard_review'
  | 'uncertain_review'
  | 'automatic_exclusion';

export type OperatorReviewQueueItem = {
  id: number;
  queue_date: string;
  run_id: number | null;
  candidate_key: string;
  lead_id: number | null;
  screening_id: number;
  screening_ids: number[];
  layer: ReviewLayer;
  reason: string;
  exclusion_sample_reason: string | null;
  position: number;
  slot_type: string;
  status: 'pending' | 'completed' | string;
  emergency: boolean;
  human_decision: string | null;
  miaoda_href: string;
  next_action: string;
};

export type OperatorReviewQueue = {
  queue_date: string;
  total: number;
  items: OperatorReviewQueueItem[];
  progress: {
    completed: number;
    target: number;
    pending: number;
    quality_control: number;
  };
};

export type ContinueReviewQueuePayload = {
  queue_date?: string;
  additional: number;
  priority_only: boolean;
  idempotency_key: string;
};

export type ContinueReviewQueueResult = {
  idempotency_key: string;
  queue_date: string | null;
  created: number;
  total: number;
  quality_control: number;
  emergency: number;
  backlog: number;
  item_ids: number[];
  candidate_keys: string[];
  priority_only: boolean;
};

export type OperatorRunCandidate = {
  run_id: number | null;
  candidate_key: string;
  lead_id: number | null;
  public_profile_id: number | null;
  representative_screening_id: number;
  screening_ids: number[];
  layer: ReviewLayer;
  reason: string;
  hard_exclusion_reason: string | null;
  intent_strength: string | null;
  confidence: number | null;
  updated_at: string;
  evidence: string[];
  status: string;
  miaoda_href: string;
  next_action: string;
};

export type OperatorRunCandidates = {
  run_id: number;
  layer: ReviewLayer | null;
  count: number;
  items: OperatorRunCandidate[];
};

export type OperatorRunReport = {
  version?: number;
  run_id: number;
  conclusion: string;
  scope: {
    campaign_id?: string | null;
    data_range?: string | null;
    source_types?: string | null;
    processed_count: number;
    candidate_count: number;
  };
  counts: Record<ReviewLayer, number>;
  exclusion_reasons: Record<string, number>;
  queue: {
    prepared: number;
    quality_control: number;
    emergency: number;
    backlog?: number;
    errors?: Array<Record<string, unknown>>;
  };
  destinations: Record<string, { status: string; detail?: string; href?: string }>;
  next_action?: { kind: string; label: string; href: string };
  technical_details: { default_collapsed: boolean; references: string[] };
};

export type OperatorCustomerSummary = {
  customer_id: number;
  customer_name: string;
  crm_stage: string;
  next_step: string | null;
  sync_version: number;
  sync_status: string;
  sync_error: string | null;
  base_record_url: string | null;
  miaoda_detail_url: string;
  updated_at: string | null;
};

export type OperatorCustomerList = {
  items: OperatorCustomerSummary[];
  count: number;
};

export type OperatorCustomerDetail = OperatorCustomerSummary & {
  platform: string;
  region: string | null;
  demand_type: string | null;
  product: string | null;
  intent_stage: string | null;
  intent_score: number;
  customer_tags: string[];
  followup_note: string | null;
  next_followup_at: string | null;
  last_contact_at: string | null;
  last_contact_result: string | null;
  profile: {
    platform_user_id: string;
    display_name: string | null;
    profile_url: string | null;
  };
  evidence: Array<{
    id: number;
    source_entity_type: string;
    source_entity_id: number;
    text: string;
  }>;
  ai_judgment: {
    screening_id: number;
    review_status: string;
    confidence: number | null;
    qualification_decision: string | null;
    campaign: string | null;
  } | null;
};

export type OperatorCustomerTimelineItem = {
  kind: 'timeline_event' | 'followup_record';
  id: number;
  event_key: string;
  occurred_at: string;
  event_type?: string;
  actor_id?: string | null;
  data?: Record<string, unknown>;
  action_type?: string;
  channel?: string | null;
  target?: string | null;
  content?: string | null;
  customer_reply?: string | null;
  result?: string | null;
  next_step?: string | null;
  next_followup_at?: string | null;
  source_entry?: string | null;
  platform_evidence?: Record<string, unknown> | null;
  is_completed?: boolean;
};

export type OperatorCustomerTimeline = {
  customer_id: number;
  items: OperatorCustomerTimelineItem[];
  count: number;
};

export type OperatorContactAttempt = {
  attempt_id: number;
  customer_id: number;
  channel: 'xiaohongshu_public_reply';
  target: { comment_id: string; url: string | null };
  draft_text: string;
  draft_revision: number;
  approved_revision: number | null;
  status: 'awaiting_approval' | 'approved' | 'queued' | 'sending' | 'sent' | 'failed' | 'result_unknown' | 'cancelled';
  safe_to_send: boolean;
  safe_to_retry: boolean;
  next_action: string;
};

export type ContactPreparationResult = {
  status: 'queued' | 'target_unavailable';
  customer_id: number;
  screening_id: number | null;
  task_id: number | null;
  task_status: 'pending' | 'running' | 'retry' | 'failed' | 'completed' | null;
  failure_reason: string | null;
};
