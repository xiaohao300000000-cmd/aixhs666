import { logger } from '@lark-apaas/client-toolkit/logger';
import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import type {
  LeadReviewAction,
  LeadReviewResult,
  OperatorErrorReason,
  OperatorLead,
  OperatorLeadQueue,
  OperatorSkillRun,
  OperatorTaskCenter,
  OperatorWorkbench,
  SkillRunParameters,
} from '../types/operator';


export async function getOperatorWorkbench(): Promise<OperatorWorkbench> {
  try {
    const response = await axiosForBackend({
      url: '/api/operator/workbench',
      method: 'GET',
    });
    return response.data as OperatorWorkbench;
  } catch (error) {
    logger.error('加载运营工作台失败', error);
    throw error;
  }
}

export async function getOperatorLeads(statusFilter = 'pending'): Promise<OperatorLeadQueue> {
  const response = await axiosForBackend({
    url: '/api/operator/leads',
    method: 'GET',
    params: { status_filter: statusFilter, limit: 100 },
  });
  return response.data as OperatorLeadQueue;
}

export async function reviewOperatorLead(
  leadId: number,
  payload: {
    action: LeadReviewAction;
    reason?: string;
    owner_name?: string;
    reviewer_id?: string;
    idempotency_key: string;
    defer_until?: string;
  },
): Promise<LeadReviewResult> {
  const response = await axiosForBackend({
    url: `/api/operator/leads/${leadId}/review`,
    method: 'POST',
    data: payload,
  });
  return response.data as LeadReviewResult;
}

export async function getOperatorTasks(): Promise<OperatorTaskCenter> {
  const response = await axiosForBackend({ url: '/api/operator/tasks', method: 'GET' });
  return response.data as OperatorTaskCenter;
}

export async function createOperatorRun(skillKey: string): Promise<OperatorSkillRun> {
  const response = await axiosForBackend({
    url: '/api/operator/tasks/runs',
    method: 'POST',
    data: { skill_key: skillKey, requested_by: 'miaoda-operator', idempotency_key: crypto.randomUUID() },
  });
  return response.data as OperatorSkillRun;
}

export async function previewOperatorRun(runId: number, parameters: SkillRunParameters): Promise<OperatorSkillRun> {
  return runAction(runId, 'preview', { parameters, event_key: crypto.randomUUID() });
}

export async function queueOperatorRun(runId: number): Promise<OperatorSkillRun> {
  return runAction(runId, 'queue', { event_key: crypto.randomUUID() });
}

export async function cancelOperatorRun(runId: number): Promise<OperatorSkillRun> {
  return runAction(runId, 'cancel', { event_key: crypto.randomUUID() });
}

export async function retryOperatorRun(runId: number): Promise<OperatorSkillRun> {
  return runAction(runId, 'retry', { event_key: crypto.randomUUID() });
}

export async function copyOperatorRun(runId: number): Promise<OperatorSkillRun> {
  return runAction(runId, 'copy', { event_key: crypto.randomUUID(), requested_by: 'miaoda-operator' });
}

async function runAction(runId: number, action: string, data: unknown): Promise<OperatorSkillRun> {
  const response = await axiosForBackend({
    url: `/api/operator/tasks/runs/${runId}/${action}`,
    method: 'POST',
    data,
  });
  return response.data as OperatorSkillRun;
}


export function getOperatorErrorReason(error: unknown): OperatorErrorReason {
  if (!error || typeof error !== 'object') {
    return 'unknown';
  }
  const response = (error as { response?: { data?: unknown } }).response;
  const data = response?.data;
  if (!data || typeof data !== 'object') {
    return 'unknown';
  }
  const directReason = (data as { reason?: unknown }).reason;
  if (isOperatorErrorReason(directReason)) {
    return directReason;
  }
  const details = (data as { error?: { details?: unknown } }).error?.details;
  if (typeof details === 'string') {
    try {
      const parsed = JSON.parse(details) as { reason?: unknown };
      if (isOperatorErrorReason(parsed.reason)) {
        return parsed.reason;
      }
    } catch {
      return 'unknown';
    }
  }
  return 'unknown';
}


function isOperatorErrorReason(value: unknown): value is Exclude<OperatorErrorReason, 'unknown'> {
  return value === 'missing_base_url' || value === 'missing_token' || value === 'backend_unreachable';
}
