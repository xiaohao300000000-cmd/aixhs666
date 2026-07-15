import { HttpService } from '@nestjs/axios';
import { Injectable, ServiceUnavailableException } from '@nestjs/common';
import type { Method } from 'axios';
import { firstValueFrom } from 'rxjs';


type ConfigurationReason = 'missing_base_url' | 'missing_token' | 'backend_unreachable';


@Injectable()
export class OperatorService {
  constructor(private readonly httpService: HttpService) {}

  async getWorkbench(): Promise<unknown> {
    return this.request('GET', '/operator/api/workbench');
  }

  async getLeads(statusFilter?: string, limit?: number): Promise<unknown> {
    return this.request('GET', '/operator/api/leads', undefined, {
      status_filter: statusFilter,
      limit,
    });
  }

  async reviewLead(leadId: number, payload: unknown): Promise<unknown> {
    return this.request('POST', `/operator/api/leads/${leadId}/review`, payload);
  }

  async getTasks(limit?: number): Promise<unknown> {
    return this.request('GET', '/operator/api/tasks', undefined, { limit });
  }

  async getRun(runId: number): Promise<unknown> {
    return this.request('GET', `/operator/api/tasks/runs/${runId}`);
  }

  async createRun(payload: unknown): Promise<unknown> {
    return this.request('POST', '/operator/api/tasks/runs', payload);
  }

  async runAction(runId: number, action: string, payload: unknown): Promise<unknown> {
    return this.request('POST', `/operator/api/tasks/runs/${runId}/${action}`, payload);
  }

  private async request(
    method: Method,
    path: string,
    data?: unknown,
    params?: Record<string, unknown>,
  ): Promise<unknown> {
    const baseUrl = process.env.OPERATOR_API_BASE_URL?.trim();
    const token = process.env.OPERATOR_API_TOKEN?.trim();
    if (!baseUrl) {
      throw this.unavailable('missing_base_url', '尚未配置运营后端地址');
    }
    if (!token) {
      throw this.unavailable('missing_token', '尚未配置运营后端访问凭证');
    }

    try {
      const response = await firstValueFrom(
        this.httpService.request({
          method,
          url: `${baseUrl.replace(/\/+$/, '')}${path}`,
          headers: { Authorization: `Bearer ${token}` },
          data,
          params,
        }),
      );
      return response.data;
    } catch (error) {
      if (error instanceof ServiceUnavailableException) {
        throw error;
      }
      throw this.unavailable('backend_unreachable', '运营后端暂时不可达，请稍后重试');
    }
  }

  private unavailable(reason: ConfigurationReason, message: string): ServiceUnavailableException {
    return new ServiceUnavailableException({
      statusCode: 503,
      code: 'OPERATOR_BACKEND_UNAVAILABLE',
      reason,
      message,
    });
  }
}
