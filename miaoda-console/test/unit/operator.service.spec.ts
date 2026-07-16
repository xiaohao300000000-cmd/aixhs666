import {
  BadRequestException,
  ConflictException,
  NotFoundException,
  ServiceUnavailableException,
  UnauthorizedException,
  UnprocessableEntityException,
} from '@nestjs/common';
import type { HttpService } from '@nestjs/axios';
import { of, throwError } from 'rxjs';
import { axiosForBackend } from '@lark-apaas/client-toolkit/utils/getAxiosForBackend';

import { OperatorService } from '../../server/modules/operator/operator.service';
import {
  approveOperatorContactAttempt,
  confirmOperatorContactNotSent,
  editOperatorContactAttempt,
  getOperatorContactErrorReason,
  sendOperatorContactAttempt,
} from '../../client/src/api/operator';
import type { OperatorContactAttempt } from '../../client/src/types/operator';


jest.mock('@lark-apaas/client-toolkit/utils/getAxiosForBackend', () => ({ axiosForBackend: jest.fn() }));
jest.mock('@lark-apaas/client-toolkit/logger', () => ({ logger: { error: jest.fn() } }));


describe('OperatorService', () => {
  const originalEnvironment = process.env;

  beforeEach(() => {
    process.env = {
      ...originalEnvironment,
      OPERATOR_API_BASE_URL: 'https://backend.example.com/',
      OPERATOR_API_TOKEN: 'server-only-secret',
    };
  });

  afterAll(() => {
    process.env = originalEnvironment;
  });

  it('loads the workbench with a server-side bearer token', async () => {
    const request = jest.fn().mockReturnValue(of({ data: { attention: { review_queue: 3 } } }));
    const service = new OperatorService({ request } as unknown as HttpService);

    const result = await service.getWorkbench();

    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        method: 'GET',
        url: 'https://backend.example.com/operator/api/workbench',
        headers: { Authorization: 'Bearer server-only-secret' },
      }),
    );
    expect(result).toEqual({ attention: { review_queue: 3 } });
    expect(JSON.stringify(result)).not.toContain('server-only-secret');
  });

  it('reports missing configuration without revealing secrets', async () => {
    delete process.env.OPERATOR_API_TOKEN;
    const service = new OperatorService({ request: jest.fn() } as unknown as HttpService);

    await expect(service.getWorkbench()).rejects.toMatchObject({
      status: 503,
      response: expect.objectContaining({ reason: 'missing_token' }),
    });
  });

  it('maps backend connection errors to a stable degraded response', async () => {
    const request = jest.fn().mockReturnValue(throwError(() => new Error('connect ECONNREFUSED server-only-secret')));
    const service = new OperatorService({ request } as unknown as HttpService);

    await expect(service.getWorkbench()).rejects.toBeInstanceOf(ServiceUnavailableException);
    await expect(service.getWorkbench()).rejects.toMatchObject({
      response: expect.objectContaining({ reason: 'backend_unreachable' }),
    });
  });

  it('proxies lead writes and task actions through the same server-side token', async () => {
    const request = jest.fn().mockReturnValue(of({ data: { ok: true } }));
    const service = new OperatorService({ request } as unknown as HttpService);

    await service.reviewLead(12, { action: 'valid' });
    await service.runAction(8, 'preview', { parameters: { limit: 10 } });

    expect(request).toHaveBeenNthCalledWith(1, expect.objectContaining({
      method: 'POST',
      url: 'https://backend.example.com/operator/api/leads/12/review',
      data: { action: 'valid' },
      headers: { Authorization: 'Bearer server-only-secret' },
    }));
    expect(request).toHaveBeenNthCalledWith(2, expect.objectContaining({
      method: 'POST',
      url: 'https://backend.example.com/operator/api/tasks/runs/8/preview',
      data: { parameters: { limit: 10 } },
    }));
  });

  it('proxies V19 read resources with their filters and the server-only token', async () => {
    const request = jest.fn().mockReturnValue(of({ data: { ok: true } }));
    const service = new OperatorService({ request } as unknown as HttpService);

    await service.getLead(214);
    await service.getReviewQueue('2026-07-16', 'priority_review', 5, 20);
    await service.getRunReport(8);
    await service.getRunCandidates(8, 'uncertain_review');
    await service.getCustomers(25);
    await service.getCustomer(147);
    await service.getCustomerTimeline(147);

    expect(request).toHaveBeenNthCalledWith(1, expect.objectContaining({
      method: 'GET',
      url: 'https://backend.example.com/operator/api/leads/214',
      headers: { Authorization: 'Bearer server-only-secret' },
    }));
    expect(request).toHaveBeenNthCalledWith(2, expect.objectContaining({
      method: 'GET',
      url: 'https://backend.example.com/operator/api/review-queue',
      params: { queue_date: '2026-07-16', layer: 'priority_review', offset: 5, limit: 20 },
      headers: { Authorization: 'Bearer server-only-secret' },
    }));
    expect(request).toHaveBeenNthCalledWith(3, expect.objectContaining({
      url: 'https://backend.example.com/operator/api/tasks/runs/8/report',
    }));
    expect(request).toHaveBeenNthCalledWith(4, expect.objectContaining({
      url: 'https://backend.example.com/operator/api/tasks/runs/8/candidates',
      params: { layer: 'uncertain_review' },
    }));
    expect(request).toHaveBeenNthCalledWith(5, expect.objectContaining({
      url: 'https://backend.example.com/operator/api/customers',
      params: { limit: 25 },
    }));
    expect(request).toHaveBeenNthCalledWith(6, expect.objectContaining({
      url: 'https://backend.example.com/operator/api/customers/147',
    }));
    expect(request).toHaveBeenNthCalledWith(7, expect.objectContaining({
      url: 'https://backend.example.com/operator/api/customers/147/timeline',
    }));
  });

  it('preserves the caller idempotency key when continuing a review queue', async () => {
    const request = jest.fn().mockReturnValue(of({ data: { created: 20 } }));
    const service = new OperatorService({ request } as unknown as HttpService);
    const payload = {
      queue_date: '2026-07-16',
      additional: 20,
      priority_only: true,
      idempotency_key: 'continue-stable-key',
    };

    await service.continueReviewQueue(payload);

    expect(request).toHaveBeenCalledWith(expect.objectContaining({
      method: 'POST',
      url: 'https://backend.example.com/operator/api/review-queue/continue',
      data: payload,
    }));
  });

  it('proxies the versioned contact workflow without replacing caller idempotency keys', async () => {
    const request = jest.fn().mockReturnValue(of({ data: { attempt_id: 41 } }));
    const service = new OperatorService({ request } as unknown as HttpService);
    const key = 'stable-contact-command';

    await service.getContactAttempt(147);
    await service.prepareContactAttempt(147, { idempotency_key: key });
    await service.editContactAttempt(147, 41, { draft_revision: 1, text: '新的公开回复', idempotency_key: key, operator: 'browser-forged-admin' });
    await service.approveContactAttempt(147, 41, { draft_revision: 2, idempotency_key: key });
    await service.sendContactAttempt(147, 41, { draft_revision: 2, confirmed: true, idempotency_key: key });
    await service.confirmContactNotSent(147, 41, { reason: '人工核验平台未发送', idempotency_key: key });

    expect(request.mock.calls.map(([input]) => [input.method, input.url, input.data])).toEqual([
      ['GET', 'https://backend.example.com/operator/api/customers/147/contact-attempt', undefined],
      ['POST', 'https://backend.example.com/operator/api/customers/147/contact-attempt/prepare', { idempotency_key: key }],
      ['PUT', 'https://backend.example.com/operator/api/customers/147/contact-attempt/41/draft', { draft_revision: 1, text: '新的公开回复', idempotency_key: key, operator: 'miaoda-operator' }],
      ['POST', 'https://backend.example.com/operator/api/customers/147/contact-attempt/41/approve', { draft_revision: 2, idempotency_key: key, operator: 'miaoda-operator' }],
      ['POST', 'https://backend.example.com/operator/api/customers/147/contact-attempt/41/send', { draft_revision: 2, confirmed: true, idempotency_key: key, operator: 'miaoda-operator' }],
      ['POST', 'https://backend.example.com/operator/api/customers/147/contact-attempt/41/confirm-not-sent', { reason: '人工核验平台未发送', idempotency_key: key, operator: 'miaoda-operator' }],
    ]);
  });

  it('emits FastAPI-compatible contact JSON from the browser client', async () => {
    const attempt = {
      attempt_id: 41,
      customer_id: 147,
      draft_revision: 2,
      draft_text: '新的公开回复',
    } as OperatorContactAttempt;
    jest.mocked(axiosForBackend).mockResolvedValue({ data: attempt } as never);

    await editOperatorContactAttempt(147, attempt, '修改文本', 'edit-key');
    await approveOperatorContactAttempt(147, attempt, 'approve-key');
    await sendOperatorContactAttempt(147, attempt, 'send-key');
    await confirmOperatorContactNotSent(147, attempt.attempt_id, '人工核验未发送', 'recover-key');

    expect(jest.mocked(axiosForBackend).mock.calls.map(([input]) => input.data)).toEqual([
      { draft_revision: 2, text: '修改文本', idempotency_key: 'edit-key' },
      { draft_revision: 2, idempotency_key: 'approve-key' },
      { draft_revision: 2, confirmed: true, idempotency_key: 'send-key' },
      { reason: '人工核验未发送', idempotency_key: 'recover-key' },
    ]);
    expect(getOperatorContactErrorReason({ response: { data: { reason: 'state_conflict' } } })).toBe('state_conflict');
  });

  it.each([
    [400, BadRequestException],
    [401, UnauthorizedException],
    [404, NotFoundException],
    [409, ConflictException],
    [422, UnprocessableEntityException],
    [503, ServiceUnavailableException],
  ])('translates backend %s into a safe actionable error', async (status, expectedType) => {
    const request = jest.fn().mockReturnValue(throwError(() => ({
      response: {
        status,
        data: {
          detail: `unsafe backend detail https://internal.example.com token=server-only-secret`,
        },
      },
      stack: 'private stack server-only-secret',
    })));
    const service = new OperatorService({ request } as unknown as HttpService);

    await expect(service.getCustomer(999)).rejects.toBeInstanceOf(expectedType);
    try {
      await service.getCustomer(999);
    } catch (error) {
      expect(JSON.stringify(error)).not.toContain('server-only-secret');
      expect(JSON.stringify(error)).not.toContain('internal.example.com');
      expect(error).toMatchObject({
        response: expect.objectContaining({ statusCode: status }),
      });
    }
  });
});
