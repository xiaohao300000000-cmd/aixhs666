import { logger } from '@lark-apaas/client-toolkit/logger';
import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import type {
  LeadReviewAction,
  LeadReviewResult,
  OperatorErrorReason,
  OperatorLead,
  OperatorLeadQueue,
  OperatorCustomerList,
  OperatorCustomerDetail,
  OperatorCustomerTimeline,
  OperatorReviewQueue,
  OperatorRunCandidates,
  OperatorRunReport,
  OperatorSkillRun,
  OperatorTaskCenter,
  OperatorWorkbench,
  SkillRunParameters,
  ContinueReviewQueuePayload,
  ContinueReviewQueueResult,
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

export async function getOperatorLead(leadId: number): Promise<OperatorLead> {
  const response = await axiosForBackend({
    url: `/api/operator/leads/${leadId}`,
    method: 'GET',
  });
  return response.data as OperatorLead;
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

export async function getOperatorRunReport(runId: number): Promise<OperatorRunReport> {
  const response = await axiosForBackend({
    url: `/api/operator/tasks/runs/${runId}/report`,
    method: 'GET',
  });
  return response.data as OperatorRunReport;
}

export async function getOperatorRunCandidates(runId: number, layer?: string): Promise<OperatorRunCandidates> {
  const response = await axiosForBackend({
    url: `/api/operator/tasks/runs/${runId}/candidates`,
    method: 'GET',
    params: { layer },
  });
  return response.data as OperatorRunCandidates;
}

export async function getOperatorReviewQueue(params: {
  queue_date?: string;
  layer?: string;
  offset?: number;
  limit?: number;
} = {}): Promise<OperatorReviewQueue> {
  const response = await axiosForBackend({
    url: '/api/operator/review-queue',
    method: 'GET',
    params,
  });
  return response.data as OperatorReviewQueue;
}

export async function continueOperatorReviewQueue(
  payload: ContinueReviewQueuePayload,
): Promise<ContinueReviewQueueResult> {
  const response = await axiosForBackend({
    url: '/api/operator/review-queue/continue',
    method: 'POST',
    data: payload,
  });
  return response.data as ContinueReviewQueueResult;
}

export async function getOperatorCustomers(limit = 100): Promise<OperatorCustomerList> {
  const response = await axiosForBackend({
    url: '/api/operator/customers',
    method: 'GET',
    params: { limit },
  });
  return response.data as OperatorCustomerList;
}

export async function getOperatorCustomer(customerId: number): Promise<OperatorCustomerDetail> {
  const response = await axiosForBackend({
    url: `/api/operator/customers/${customerId}`,
    method: 'GET',
  });
  return response.data as OperatorCustomerDetail;
}

export async function getOperatorCustomerTimeline(customerId: number): Promise<OperatorCustomerTimeline> {
  const response = await axiosForBackend({
    url: `/api/operator/customers/${customerId}/timeline`,
    method: 'GET',
  });
  return response.data as OperatorCustomerTimeline;
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
  return [
    'missing_base_url',
    'missing_token',
    'backend_unreachable',
    'backend_unavailable',
    'backend_unauthorized',
    'invalid_request',
    'resource_not_found',
    'validation_failed',
  ].includes(String(value));
}
