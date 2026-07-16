import type {
  AttentionCounts,
  LeadReviewAction,
  OperatorCustomerList,
  OperatorCustomerSummary,
  OperatorCustomerTimeline,
  OperatorContactAttempt,
  OperatorErrorReason,
  CustomerProgression,
  OperatorReviewQueueItem,
  OperatorReviewQueue,
  OperatorRunReport,
  OperatorSkillRun,
  OperatorWorkbench,
  WorkerItem,
} from '../../types/operator';


export type StatusTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

export type AttentionItem = {
  key: keyof AttentionCounts;
  label: string;
  value: number;
  description: string;
  tone: StatusTone;
};


export function buildAttentionItems(attention: AttentionCounts): AttentionItem[] {
  return [
    {
      key: 'failed_tasks',
      label: '失败任务',
      value: attention.failed_tasks,
      description: attention.failed_tasks ? '需要检查并恢复' : '暂无失败任务',
      tone: attention.failed_tasks ? 'danger' : 'success',
    },
    {
      key: 'review_queue',
      label: '待审核线索',
      value: attention.review_queue,
      description: attention.review_queue ? '等待人工判断' : '审核队列已清空',
      tone: attention.review_queue ? 'warning' : 'success',
    },
    {
      key: 'stale_workers',
      label: '异常 Worker',
      value: attention.stale_workers,
      description: attention.stale_workers ? '心跳超过五分钟' : 'Worker 状态正常',
      tone: attention.stale_workers ? 'danger' : 'success',
    },
    {
      key: 'running_skills',
      label: '运行中任务',
      value: attention.running_skills,
      description: attention.running_skills ? '正在处理数据' : '当前没有运行任务',
      tone: attention.running_skills ? 'info' : 'neutral',
    },
  ];
}


export function isWorkbenchEmpty(workbench: OperatorWorkbench): boolean {
  return Object.values(workbench.attention).every((value) => value === 0)
    && workbench.lead_queue.length === 0
    && workbench.skill_runs.length === 0
    && workbench.task_failures.length === 0
    && workbench.workers.length === 0;
}


export function getWorkerHealthTone(health: WorkerItem['health']): StatusTone {
  return health === 'stale' ? 'danger' : 'success';
}


export function formatRelativeTime(value: string | null): string {
  if (!value) {
    return '暂无时间';
  }
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return '时间未知';
  }
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) {
    return '刚刚';
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes} 分钟前`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} 小时前`;
  }
  return `${Math.floor(hours / 24)} 天前`;
}


export function leadActionRequiresReason(action: LeadReviewAction): boolean {
  return action === 'reject' || action === 'defer';
}


export function getNextLeadId(items: Array<{ id: number }>, currentId: number): number | null {
  const index = items.findIndex((item) => item.id === currentId);
  if (index < 0) {
    return items[0]?.id ?? null;
  }
  return items[index + 1]?.id ?? items[index - 1]?.id ?? null;
}


export function getRunStatusLabel(status: string): string {
  return {
    draft: '待配置',
    previewed: '已预览',
    queued: '排队中',
    running: '运行中',
    cancel_requested: '取消中',
    cancelled: '已取消',
    succeeded: '已完成',
    failed: '失败',
    result_uncertain: '结果待确认',
  }[status] ?? status;
}


export function getRunActions(run: OperatorSkillRun): string[] {
  if (run.status === 'draft') return ['preview', 'cancel'];
  if (run.status === 'previewed') return ['queue', 'cancel', 'copy'];
  if (run.status === 'queued' || run.status === 'running') return ['cancel'];
  if (run.status === 'failed') return ['retry', 'copy'];
  return ['copy'];
}

export function buildTodayActionModel({
  workbench,
  reviewQueue,
  customers,
  recentReport,
}: {
  workbench: OperatorWorkbench;
  reviewQueue: OperatorReviewQueue;
  customers: OperatorCustomerList;
  recentReport: OperatorRunReport | null;
}) {
  const pendingItems = reviewQueue.items.filter((item) => item.status === 'pending');
  const layerCount = (layer: string) => pendingItems.filter((item) => item.layer === layer).length;
  const priority = layerCount('priority_review');
  const standard = layerCount('standard_review');
  const uncertain = layerCount('uncertain_review');
  const health = buildSystemHealthModel(workbench);
  const hasUnknownFailures = workbench.attention.failed_tasks > 0 && workbench.task_failures.length === 0;
  let primaryAction = {
    kind: 'none',
    title: '今天的业务动作已处理完',
    description: '可以查看最近任务结果或客户状态。',
    href: '/tasks',
  };
  if (hasUnknownFailures || health.blockingFailures.length > 0) {
    const blockingCount = health.blockingFailures.length || workbench.attention.failed_tasks;
    primaryAction = {
      kind: 'blocking_failure',
      title: '先确认阻塞业务的异常',
      description: `${blockingCount} 个失败任务需要确认影响与恢复方式。`,
      href: '/system-health',
    };
  } else if (priority > 0) {
    primaryAction = {
      kind: 'priority_review',
      title: `先审核 ${priority} 条高优先级候选`,
      description: '这些候选的需求信号最强，处理后自动进入下一条。',
      href: `/leads?queue_date=${reviewQueue.queue_date}&layer=priority_review`,
    };
  } else if (standard > 0 || uncertain > 0) {
    const layer = standard > 0 ? 'standard_review' : 'uncertain_review';
    primaryAction = {
      kind: layer,
      title: standard > 0 ? `继续审核 ${standard} 条普通候选` : `完成 ${uncertain} 条不确定与质检候选`,
      description: '当前入口保留业务日与分层，刷新后不会丢失批次。',
      href: `/leads?queue_date=${reviewQueue.queue_date}&layer=${layer}`,
    };
  }
  return {
    primaryAction,
    reviewProgress: {
      completed: reviewQueue.progress.completed,
      target: reviewQueue.progress.target,
      pending: reviewQueue.progress.pending,
      qualityControl: reviewQueue.progress.quality_control,
    },
    reviewLayers: { priority, standard, uncertain },
    customerMetrics: {
      total: customers.count,
      awaitingFirstContact: customers.items.filter((item) => ['new_customer', 'awaiting_first_contact'].includes(item.crm_stage)).length,
      contactedWaitingReply: customers.items.filter((item) => ['contacted_waiting_reply', 'awaiting_reply'].includes(item.crm_stage)).length,
      dueFollowups: null as number | null,
    },
    recentReport: recentReport ? buildRunReportView(recentReport) : null,
    unavailableCapabilities: [
      { key: 'approved_send', label: '已确认待发送', enabled: false, note: 'V19-05 开放' },
      { key: 'reply_check', label: '客户新回复', enabled: false, note: 'V19-06 开放' },
      { key: 'automatic_schedule', label: '14:00 / 15:00 / 21:00 自动调度', enabled: false, note: 'V19-06 开放' },
    ],
  };
}

export function buildRunReportView(report: OperatorRunReport) {
  const candidateHref = (layer: string) => `/tasks?run_id=${report.run_id}&layer=${layer}`;
  return {
    runId: report.run_id,
    conclusion: report.conclusion,
    funnel: [
      { key: 'processed', label: '分析内容', value: report.scope.processed_count, href: null },
      { key: 'priority_review', label: '高优先级候选', value: report.counts.priority_review ?? 0, href: candidateHref('priority_review') },
      { key: 'standard_review', label: '普通候选', value: report.counts.standard_review ?? 0, href: candidateHref('standard_review') },
      { key: 'uncertain_review', label: '不确定候选', value: report.counts.uncertain_review ?? 0, href: candidateHref('uncertain_review') },
      { key: 'automatic_exclusion', label: '自动排除', value: report.counts.automatic_exclusion ?? 0, href: candidateHref('automatic_exclusion') },
      { key: 'review_queue', label: '进入今日审核', value: report.queue.prepared ?? 0, href: `/leads?run_id=${report.run_id}` },
    ],
    destinations: Object.entries(report.destinations).map(([key, value]) => ({ key, ...value })),
    exclusionReasons: Object.entries(report.exclusion_reasons),
    technicalDetails: report.technical_details,
  };
}

export type RunReportAvailability = {
  kind: 'not_expected' | 'loading' | 'available' | 'missing' | 'credentials' | 'unavailable';
  title: string;
  description: string | null;
};

export function buildRunReportAvailability({
  runStatus,
  hasReport,
  isLoading,
  isError,
  errorReason,
}: {
  runStatus: string;
  hasReport: boolean;
  isLoading: boolean;
  isError: boolean;
  errorReason: OperatorErrorReason | null;
}): RunReportAvailability {
  if (runStatus !== 'succeeded') {
    return { kind: 'not_expected', title: getRunStatusLabel(runStatus), description: null };
  }
  if (hasReport) {
    return { kind: 'available', title: '业务报告已生成', description: null };
  }
  if (isLoading || !isError) {
    return { kind: 'loading', title: '正在加载业务报告', description: '正在读取本次任务的业务结论，请稍候。' };
  }
  if (errorReason === 'resource_not_found') {
    return { kind: 'missing', title: '历史业务报告不存在', description: '该历史任务尚未生成业务报告。原始成功状态不会替代业务结论。' };
  }
  if (errorReason === 'backend_unauthorized' || errorReason === 'missing_token') {
    return { kind: 'credentials', title: '业务报告凭证需要检查', description: '当前无法读取业务报告，请检查服务端访问凭证后重试。' };
  }
  return { kind: 'unavailable', title: '业务报告暂时不可达', description: '当前无法确认本次任务的业务结论，请稍后重试。' };
}

export function buildReviewLocation({
  queueDate,
  runId,
  layer,
  candidateKey,
  position,
}: {
  queueDate?: string | null;
  runId?: number | null;
  layer?: string | null;
  candidateKey?: string | null;
  position?: number | null;
}): string {
  const params = new URLSearchParams();
  if (queueDate) params.set('queue_date', queueDate);
  if (runId) params.set('run_id', String(runId));
  if (layer) params.set('layer', layer);
  if (candidateKey) params.set('candidate_key', candidateKey);
  if (position) params.set('position', String(position));
  const query = params.toString();
  return query ? `/leads?${query}` : '/leads';
}

export function getNextPendingQueueCandidateKey(
  items: Array<{ candidate_key: string; status: string }>,
  currentKey: string,
): string | null {
  const currentIndex = items.findIndex((item) => item.candidate_key === currentKey);
  const forward = items.slice(Math.max(0, currentIndex + 1)).find((item) => item.status === 'pending' && item.candidate_key !== currentKey);
  if (forward) return forward.candidate_key;
  const wrapLimit = currentIndex < 0 ? items.length : currentIndex;
  return items.slice(0, wrapLimit).find((item) => item.status === 'pending' && item.candidate_key !== currentKey)?.candidate_key ?? null;
}

export type ReviewBatchView = {
  state: 'run_loading' | 'run_unavailable' | 'daily_loading' | 'daily_missing' | 'daily_unavailable' | 'empty' | 'complete' | 'ready';
  items: OperatorReviewQueueItem[];
  title: string | null;
  description: string | null;
};

export function resolveReviewBatch({
  runId,
  runItems,
  dailyItems,
  runLoading,
  runErrorReason,
  dailyLoading,
  dailyErrorReason,
}: {
  runId: number | null;
  runItems?: OperatorReviewQueueItem[];
  dailyItems?: OperatorReviewQueueItem[];
  runLoading: boolean;
  runErrorReason: OperatorErrorReason | null;
  dailyLoading: boolean;
  dailyErrorReason: OperatorErrorReason | null;
}): ReviewBatchView {
  const isRunBatch = runId !== null;
  if (isRunBatch && runErrorReason) {
    return { state: 'run_unavailable', items: [], title: '本次任务候选暂时不可达', description: '无法读取该 Run 的候选；页面不会回退到今日队列。请稍后重试。' };
  }
  if (isRunBatch && (runLoading || runItems === undefined)) {
    return { state: 'run_loading', items: [], title: '正在加载本次任务候选', description: '正在读取该 Run 的候选，加载完成前不会开放审核动作。' };
  }
  if (!isRunBatch && dailyErrorReason === 'resource_not_found') {
    return { state: 'daily_missing', items: [], title: '今日审核队列尚未生成', description: '当前业务日没有已生成的审核队列。' };
  }
  if (!isRunBatch && dailyErrorReason) {
    return { state: 'daily_unavailable', items: [], title: '审核队列暂时不可达', description: '请确认运营后端在线后重试；页面不会使用演示候选。' };
  }
  if (!isRunBatch && (dailyLoading || dailyItems === undefined)) {
    return { state: 'daily_loading', items: [], title: '正在加载今日审核队列', description: '正在读取真实审核队列，请稍候。' };
  }
  const items = (isRunBatch ? runItems : dailyItems) ?? [];
  if (items.length === 0) {
    return {
      state: 'empty',
      items,
      title: isRunBatch ? '本次任务没有可显示候选' : '今日审核队列为空',
      description: isRunBatch ? '返回任务结果查看分层与排除原因。' : '如已完成今日目标，可以选择继续审核 20 条。',
    };
  }
  if (!items.some((item) => item.status === 'pending')) {
    return {
      state: 'complete',
      items,
      title: isRunBatch ? '本次任务候选已全部完成' : '今日队列已全部完成',
      description: isRunBatch ? '返回任务结果选择其他批次。' : '可以继续审核 20 条，或回到工作台处理客户行动。',
    };
  }
  return { state: 'ready', items, title: null, description: null };
}

export function selectReviewCandidate(batch: ReviewBatchView, currentKey: string | null): OperatorReviewQueueItem | null {
  if (batch.state !== 'ready') return null;
  return batch.items.find((item) => item.candidate_key === currentKey)
    ?? batch.items.find((item) => item.status === 'pending')
    ?? null;
}

export function reviewQueueWritesEnabled(batch: ReviewBatchView): boolean {
  return ['ready', 'empty', 'complete'].includes(batch.state);
}

export type StableRequestIdentity = { signature: string; key: string };

export function reuseIdempotencyKey(
  current: StableRequestIdentity | null,
  signature: string,
  createKey: () => string,
): StableRequestIdentity {
  if (current?.signature === signature) return current;
  return { signature, key: createKey() };
}

export function buildReviewOutcome({
  progression,
  baseStatus,
}: {
  progression: CustomerProgression;
  baseStatus?: string | null;
}) {
  const stage = ({ awaiting_first_contact: '待首次联系', deferred: '已暂缓', invalid: '无效' } as Record<string, string>)[progression.customer_stage] ?? progression.customer_stage;
  const base = baseStatus === 'synced' ? 'Base CRM 已同步' : baseStatus === 'failed' ? 'Base CRM 同步失败' : 'Base CRM 状态待确认';
  return {
    summary: `已处理客户 #${progression.customer_id}｜当前阶段：${stage}｜${base}`,
    boundary: '公开回复草稿功能将在 V19-05 开放',
    customerHref: `/customers/${progression.customer_id}`,
  };
}

export function buildCustomerSummaryView(customer: OperatorCustomerSummary) {
  const stages: Record<string, string> = {
    new_customer: '新客户',
    awaiting_first_contact: '待首次联系',
    draft_confirmed: '话术已确认',
    waiting_to_send: '等待发送',
    contacted_waiting_reply: '已联系待回复',
    customer_replied: '客户已回复',
    communicating: '沟通中',
    qualified_intent: '有明确意向',
    converted: '已转化',
    deferred: '暂缓',
    temporarily_unreachable: '暂时失联',
    invalid: '无效',
  };
  const syncLabels: Record<string, string> = {
    synced: 'Base CRM 已同步',
    pending: customer.base_record_url ? '等待再次同步' : '尚未同步到 Base',
    failed: 'Base CRM 同步失败',
    reconciliation_unknown: 'Base 同步结果待核对',
  };
  return {
    id: customer.customer_id,
    name: customer.customer_name || `客户 #${customer.customer_id}`,
    stageLabel: stages[customer.crm_stage] ?? customer.crm_stage,
    nextStep: customer.next_step || '下一步尚未安排',
    syncLabel: syncLabels[customer.sync_status] ?? `同步状态：${customer.sync_status}`,
    syncTone: customer.sync_status === 'synced' ? 'success' : customer.sync_status === 'failed' ? 'danger' : 'warning',
    baseAvailable: Boolean(customer.base_record_url),
    baseHref: customer.base_record_url,
    miaodaHref: `/customers/${customer.customer_id}`,
    updatedAt: customer.updated_at,
  };
}

export function buildCustomerTimelineView(timeline: OperatorCustomerTimeline) {
  return timeline.items.map((item) => {
    if (item.kind === 'timeline_event') {
      const title = ({
        candidate_promoted: '已推进为客户',
        candidate_deferred: '候选已暂缓',
        candidate_rejected: '候选已淘汰',
        crm_stage_changed: 'CRM 阶段已更新',
        customer_crm_synced: 'Base CRM 已同步',
      } as Record<string, string>)[item.event_type || ''] ?? '客户事实已更新';
      const reason = typeof item.data?.reason === 'string' ? item.data.reason : '业务事实已写入 PostgreSQL';
      return { id: `${item.kind}-${item.id}`, title, description: reason, occurredAt: item.occurred_at, raw: item };
    }
    const title = ({
      first_contact_due: '首次联系待处理',
      new_customer: '新客户跟进已建立',
      新客户: '新客户跟进已建立',
      contact_attempt: '已记录一次联系',
      customer_reply: '客户有新回复',
    } as Record<string, string>)[item.action_type || ''] ?? '跟进记录已更新';
    const description = item.next_step || item.result || item.content || '跟进事实已保留';
    return { id: `${item.kind}-${item.id}`, title, description, occurredAt: item.occurred_at, raw: item };
  });
}

export function buildContactAttemptView(attempt: OperatorContactAttempt) {
  const exactApprovedRevision = attempt.approved_revision === attempt.draft_revision;
  const active = ['queued', 'sending'].includes(attempt.status);
  return {
    statusLabel: ({
      awaiting_approval: '话术待确认', approved: '话术已确认，等待最终发送', queued: '发送任务已排队', sending: '正在发送',
      sent: '已发送', failed: '发送失败', result_unknown: '发送结果待人工核验', cancelled: '已取消',
    } as Record<string, string>)[attempt.status] ?? attempt.status,
    canEdit: !active && !['sent', 'result_unknown', 'cancelled'].includes(attempt.status),
    canApprove: !active && !['sent', 'result_unknown', 'cancelled'].includes(attempt.status) && (!exactApprovedRevision || !attempt.safe_to_send),
    canSend: attempt.status === 'approved' && exactApprovedRevision && attempt.safe_to_send,
    canRecover: attempt.status === 'result_unknown',
    directMessageAvailable: false,
  };
}

export function buildSystemHealthModel(workbench: OperatorWorkbench) {
  const blockingTypes = new Set(['skill_run_execute', 'comment_reply_send', 'outreach_send']);
  const failures = workbench.task_failures.map((failure) => ({
    id: failure.id,
    blocking: blockingTypes.has(failure.task_type),
    title: blockingTypes.has(failure.task_type) ? '业务任务执行失败' : '非阻塞后台任务失败',
    summary: sanitizeOperatorErrorSummary(failure.last_error),
    attempts: `${failure.attempt_count} / ${failure.max_attempts}`,
    updatedAt: failure.updated_at,
    href: '/tasks',
  }));
  return {
    connection: {
      status: 'connected',
      label: 'Operator 后端已连接',
      lastSuccessAt: workbench.generated_at,
    },
    workers: workbench.workers.map((worker) => ({
      id: worker.worker_id,
      label: worker.health === 'stale' ? '需要恢复' : '运行正常',
      currentTask: worker.current_task_id ? `任务 #${worker.current_task_id}` : '当前无任务',
      lastHeartbeatAt: worker.last_heartbeat_at,
      completed: worker.completed_task_count,
      failed: worker.failed_task_count,
    })),
    blockingFailures: failures.filter((failure) => failure.blocking),
    nonBlockingFailures: failures.filter((failure) => !failure.blocking),
    integrations: [
      { key: 'base', label: 'Base CRM', status: '未提供状态' },
      { key: 'feishu', label: '飞书提醒', status: '未提供状态' },
    ],
  };
}

export function sanitizeOperatorErrorSummary(value: string | null): string {
  if (!value) return '后端未提供安全错误摘要';
  return value
    .split('\n')[0]
    .replace(/authorization\s*[=:]\s*bearer\s+\S+/gi, 'Authorization=[敏感信息已隐藏]')
    .replace(/https?:\/\/\S+/gi, '[内部地址已隐藏]')
    .replace(/(?:\/Users|\/home|\/var|\/tmp)\/[^;\s]+/g, '[本机路径已隐藏]')
    .replace(/\b(?:\.{0,2}\/)?third_party\/[^;\s'\"]+/gi, '[本机路径已隐藏]')
    .replace(/(['"])(?:\.{0,2}\/)?(?:[\w.-]+\/)+[\w./-]+\1/g, "'[本机路径已隐藏]'")
    .replace(/(?:stderr=)?Traceback\b.*$/gi, '[错误堆栈已隐藏]')
    .replace(/(token|secret|authorization|password)\s*[=:]\s*\S+/gi, '$1=[敏感信息已隐藏]')
    .slice(0, 180);
}
