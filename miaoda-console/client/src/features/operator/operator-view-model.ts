import type { AttentionCounts, LeadReviewAction, OperatorSkillRun, OperatorWorkbench, WorkerItem } from '../../types/operator';


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
