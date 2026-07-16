import {
  buildAttentionItems,
  buildRunReportView,
  buildTodayActionModel,
  buildReviewLocation,
  buildReviewOutcome,
  buildCustomerSummaryView,
  buildCustomerTimelineView,
  buildSystemHealthModel,
  getNextLeadId,
  getNextPendingQueueCandidateKey,
  getRunActions,
  getRunStatusLabel,
  getWorkerHealthTone,
  isWorkbenchEmpty,
  leadActionRequiresReason,
  reuseIdempotencyKey,
} from '../../client/src/features/operator/operator-view-model';
import type {
  OperatorCustomerList,
  OperatorReviewQueue,
  OperatorRunReport,
  OperatorSkillRun,
  OperatorWorkbench,
} from '../../client/src/types/operator';


const emptyWorkbench: OperatorWorkbench = {
  generated_at: '2026-07-15T01:00:00+00:00',
  attention: {
    review_queue: 0,
    running_skills: 0,
    failed_tasks: 0,
    stale_workers: 0,
  },
  lead_queue: [],
  skill_runs: [],
  task_failures: [],
  workers: [],
  next_action: {
    kind: 'none',
    title: '当前没有紧急事项',
    description: '系统队列平稳。',
    target: '/campaigns',
  },
};


describe('operator view model', () => {
  it('prioritizes failed tasks as urgent attention', () => {
    const items = buildAttentionItems({
      ...emptyWorkbench.attention,
      review_queue: 8,
      failed_tasks: 2,
    });

    expect(items[0]).toMatchObject({ key: 'failed_tasks', tone: 'danger', value: 2 });
    expect(items[1]).toMatchObject({ key: 'review_queue', tone: 'warning', value: 8 });
  });

  it('formats an empty workbench without fake metrics', () => {
    expect(isWorkbenchEmpty(emptyWorkbench)).toBe(true);
    expect(buildAttentionItems(emptyWorkbench.attention).map((item) => item.value)).toEqual([0, 0, 0, 0]);
  });

  it('marks stale workers as degraded', () => {
    expect(getWorkerHealthTone('stale')).toBe('danger');
    expect(getWorkerHealthTone('healthy')).toBe('success');
  });

  it('advances lead review and enforces reasoned judgments', () => {
    expect(getNextLeadId([{ id: 1 }, { id: 2 }, { id: 3 }], 2)).toBe(3);
    expect(leadActionRequiresReason('reject')).toBe(true);
    expect(leadActionRequiresReason('defer')).toBe(true);
    expect(leadActionRequiresReason('promote')).toBe(false);
  });

  it('maps run states to operator actions', () => {
    const run = { status: 'previewed' } as OperatorSkillRun;
    expect(getRunStatusLabel('previewed')).toBe('已预览');
    expect(getRunActions(run)).toEqual(['queue', 'cancel', 'copy']);
  });

  it('builds the primary action from blocking failures before review work', () => {
    const queue = {
      queue_date: '2026-07-16',
      total: 50,
      progress: { completed: 8, target: 50, pending: 42, quality_control: 5 },
      items: [
        { id: 1, layer: 'priority_review', status: 'pending' },
        { id: 2, layer: 'uncertain_review', status: 'pending' },
      ],
    } as OperatorReviewQueue;
    const customers = {
      count: 2,
      items: [
        { customer_id: 147, crm_stage: 'new_customer' },
        { customer_id: 148, crm_stage: 'contacted_waiting_reply' },
      ],
    } as OperatorCustomerList;

    const model = buildTodayActionModel({
      workbench: { ...emptyWorkbench, attention: { ...emptyWorkbench.attention, failed_tasks: 1 } },
      reviewQueue: queue,
      customers,
      recentReport: null,
    });

    expect(model.primaryAction).toMatchObject({
      kind: 'blocking_failure',
      href: '/system-health',
    });
    expect(model.reviewProgress).toEqual({ completed: 8, target: 50, pending: 42, qualityControl: 5 });
    expect(model.reviewLayers).toEqual({ priority: 1, standard: 0, uncertain: 1 });
    expect(model.customerMetrics).toEqual({
      total: 2,
      awaitingFirstContact: 1,
      contactedWaitingReply: 1,
      dueFollowups: null,
    });
    expect(model.unavailableCapabilities).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: 'approved_send', enabled: false }),
      expect.objectContaining({ key: 'reply_check', enabled: false }),
      expect.objectContaining({ key: 'automatic_schedule', enabled: false }),
    ]));
  });

  it('uses a stable queue deep link for the highest pending review layer', () => {
    const model = buildTodayActionModel({
      workbench: emptyWorkbench,
      reviewQueue: {
        queue_date: '2026-07-16',
        total: 2,
        progress: { completed: 0, target: 2, pending: 2, quality_control: 1 },
        items: [
          { id: 1, layer: 'priority_review', status: 'pending' },
          { id: 2, layer: 'uncertain_review', status: 'pending' },
        ],
      } as OperatorReviewQueue,
      customers: { count: 0, items: [] },
      recentReport: null,
    });

    expect(model.primaryAction).toMatchObject({
      kind: 'priority_review',
      href: '/leads?queue_date=2026-07-16&layer=priority_review',
    });
  });

  it('maps a human run report into drillable business funnel rows', () => {
    const report = {
      run_id: 8,
      conclusion: '本次分析 50 条公开内容，合并得到 49 个待审核候选。',
      scope: { processed_count: 50, candidate_count: 50 },
      counts: {
        priority_review: 1,
        standard_review: 2,
        uncertain_review: 46,
        automatic_exclusion: 1,
      },
      queue: { prepared: 50, quality_control: 5, emergency: 0 },
      destinations: {
        postgresql: { status: 'persisted', detail: '已保留' },
        miaoda: { status: 'ready', href: '/leads?run_id=8' },
        base: { status: 'synced', detail: '已同步' },
        feishu: { status: 'summary_ready' },
      },
      exclusion_reasons: { 明确广告: 1 },
      technical_details: { default_collapsed: true, references: ['checkpoint_json'] },
    } as OperatorRunReport;

    const model = buildRunReportView(report);

    expect(model.conclusion).toContain('49 个待审核候选');
    expect(model.funnel.map((item) => [item.key, item.value, item.href])).toEqual([
      ['processed', 50, null],
      ['priority_review', 1, '/tasks?run_id=8&layer=priority_review'],
      ['standard_review', 2, '/tasks?run_id=8&layer=standard_review'],
      ['uncertain_review', 46, '/tasks?run_id=8&layer=uncertain_review'],
      ['automatic_exclusion', 1, '/tasks?run_id=8&layer=automatic_exclusion'],
      ['review_queue', 50, '/leads?run_id=8'],
    ]);
    expect(model.destinations.find((item) => item.key === 'base')).toMatchObject({ status: 'synced' });
    expect(model.technicalDetails.references).toEqual(['checkpoint_json']);
  });

  it('preserves the review batch and current candidate in the URL', () => {
    expect(buildReviewLocation({
      queueDate: '2026-07-16',
      runId: 8,
      layer: 'uncertain_review',
      candidateKey: 'profile:147',
      position: 12,
    })).toBe('/leads?queue_date=2026-07-16&run_id=8&layer=uncertain_review&candidate_key=profile%3A147&position=12');
  });

  it('advances only to the next pending queue item', () => {
    const items = [
      { candidate_key: 'profile:1', status: 'completed' },
      { candidate_key: 'profile:2', status: 'pending' },
      { candidate_key: 'profile:3', status: 'completed' },
      { candidate_key: 'profile:4', status: 'pending' },
    ];

    expect(getNextPendingQueueCandidateKey(items, 'profile:2')).toBe('profile:4');
    expect(getNextPendingQueueCandidateKey(items, 'profile:4')).toBeNull();
  });

  it('reuses an idempotency key for the same failed submission signature', () => {
    const first = reuseIdempotencyKey(null, 'promote:profile:147', () => 'key-1');
    const retry = reuseIdempotencyKey(first, 'promote:profile:147', () => 'key-2');
    const changed = reuseIdempotencyKey(first, 'reject:profile:147:irrelevant', () => 'key-3');

    expect(retry).toBe(first);
    expect(changed).toEqual({ signature: 'reject:profile:147:irrelevant', key: 'key-3' });
  });

  it('describes concrete review consequences without claiming public reply delivery', () => {
    const outcome = buildReviewOutcome({
      progression: {
        customer_id: 147,
        customer_stage: 'awaiting_first_contact',
        next_action: 'prepare_public_reply',
        timeline_event_id: 3,
        timeline_event_type: 'candidate_promoted',
        screening_id: 8,
        idempotent_replay: false,
      },
      baseStatus: 'synced',
    });

    expect(outcome.summary).toContain('客户 #147');
    expect(outcome.summary).toContain('Base CRM 已同步');
    expect(outcome.boundary).toBe('公开回复草稿功能将在 V19-05 开放');
    expect(outcome.customerHref).toBe('/customers/147');
  });

  it('maps customer stages and missing Base mappings without fake success', () => {
    const model = buildCustomerSummaryView({
      customer_id: 147,
      customer_name: '客户 A',
      crm_stage: 'new_customer',
      next_step: '准备首次联系',
      sync_version: 2,
      sync_status: 'pending',
      sync_error: null,
      base_record_url: null,
      miaoda_detail_url: '/customers/147',
      updated_at: '2026-07-16T08:00:00Z',
    });

    expect(model.stageLabel).toBe('新客户');
    expect(model.syncLabel).toBe('尚未同步到 Base');
    expect(model.baseAvailable).toBe(false);
    expect(model.nextStep).toBe('准备首次联系');
  });

  it('translates customer timeline facts while retaining raw details separately', () => {
    const model = buildCustomerTimelineView({
      customer_id: 147,
      count: 2,
      items: [
        {
          kind: 'timeline_event',
          id: 1,
          event_key: 'promote:1',
          event_type: 'candidate_promoted',
          actor_id: 'operator-1',
          data: { reason: '需求明确' },
          occurred_at: '2026-07-16T08:00:00Z',
        },
        {
          kind: 'followup_record',
          id: 2,
          event_key: 'followup:2',
          action_type: 'first_contact_due',
          channel: null,
          target: null,
          content: null,
          customer_reply: null,
          result: 'pending',
          next_step: '准备公开回复',
          next_followup_at: null,
          source_entry: 'customer_progression',
          platform_evidence: null,
          is_completed: false,
          occurred_at: '2026-07-16T08:05:00Z',
        },
      ],
    });

    expect(model.map((item) => item.title)).toEqual(['已推进为客户', '首次联系待处理']);
    expect(model[0].description).toContain('需求明确');
    expect(model[1].description).toContain('准备公开回复');
    expect(model[0].raw).toMatchObject({ event_type: 'candidate_promoted' });
  });

  it('translates the live Chinese new-customer follow-up fact', () => {
    const model = buildCustomerTimelineView({
      customer_id: 147,
      count: 1,
      items: [{
        kind: 'followup_record',
        id: 4,
        event_key: 'crm-migration-customer:147',
        action_type: '新客户',
        result: 'completed',
        next_step: '查看证据原文，准备人工跟进',
        occurred_at: '2026-07-16T12:05:44Z',
      }],
    });

    expect(model[0].title).toBe('新客户跟进已建立');
  });

  it('separates blocking and non-blocking failures and sanitizes technical errors', () => {
    const model = buildSystemHealthModel({
      ...emptyWorkbench,
      attention: { ...emptyWorkbench.attention, failed_tasks: 2, stale_workers: 1 },
      task_failures: [
        {
          id: 1,
          task_type: 'skill_run_execute',
          platform: 'internal',
          target_id: '8',
          attempt_count: 2,
          max_attempts: 3,
          last_error: 'POST https://internal.example.com token=server-only-secret\nprivate stack',
          finished_at: null,
          updated_at: '2026-07-16T08:00:00Z',
        },
        {
          id: 2,
          task_type: 'search',
          platform: 'xhs',
          target_id: null,
          attempt_count: 1,
          max_attempts: 3,
          last_error: 'timeout',
          finished_at: null,
          updated_at: '2026-07-16T08:00:00Z',
        },
      ],
      workers: [{
        worker_id: 'worker-1',
        status: 'idle',
        health: 'stale',
        current_task_id: null,
        completed_task_count: 3,
        failed_task_count: 1,
        last_error: null,
        last_heartbeat_at: '2026-07-16T07:00:00Z',
      }],
    });

    expect(model.blockingFailures).toHaveLength(1);
    expect(model.nonBlockingFailures).toHaveLength(1);
    expect(model.blockingFailures[0].summary).not.toContain('internal.example.com');
    expect(model.blockingFailures[0].summary).not.toContain('server-only-secret');
    expect(model.workers).toEqual([expect.objectContaining({ label: '需要恢复', currentTask: '当前无任务' })]);
    expect(model.integrations).toEqual([
      { key: 'base', label: 'Base CRM', status: '未提供状态' },
      { key: 'feishu', label: '飞书提醒', status: '未提供状态' },
    ]);
  });
});
