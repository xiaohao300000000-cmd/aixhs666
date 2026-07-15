import { ServiceUnavailableException } from '@nestjs/common';
import type { HttpService } from '@nestjs/axios';
import { of, throwError } from 'rxjs';

import { OperatorService } from '../../server/modules/operator/operator.service';


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
});
