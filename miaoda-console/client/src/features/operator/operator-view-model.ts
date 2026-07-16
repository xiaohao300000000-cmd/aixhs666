import type {
  AttentionCounts,
  LeadReviewAction,
  OperatorCustomerList,
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
  let primaryAction = {
    kind: 'none',
    title: '今天的业务动作已处理完',
    description: '可以查看最近任务结果或客户状态。',
    href: '/tasks',
  };
  if (workbench.attention.failed_tasks > 0) {
    primaryAction = {
      kind: 'blocking_failure',
      title: '先确认阻塞业务的异常',
      description: `${workbench.attention.failed_tasks} 个失败任务需要确认影响与恢复方式。`,
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
