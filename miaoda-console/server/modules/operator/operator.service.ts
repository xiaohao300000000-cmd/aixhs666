import { HttpService } from '@nestjs/axios';
import {
  BadRequestException,
  ConflictException,
  HttpException,
  Injectable,
  NotFoundException,
  ServiceUnavailableException,
  UnauthorizedException,
  UnprocessableEntityException,
} from '@nestjs/common';
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

  async getLead(leadId: number): Promise<unknown> {
    return this.request('GET', `/operator/api/leads/${leadId}`);
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

  async getRunReport(runId: number): Promise<unknown> {
    return this.request('GET', `/operator/api/tasks/runs/${runId}/report`);
  }

  async getRunCandidates(runId: number, layer?: string): Promise<unknown> {
    return this.request('GET', `/operator/api/tasks/runs/${runId}/candidates`, undefined, { layer });
  }

  async getReviewQueue(
    queueDate?: string,
    layer?: string,
    offset?: number,
    limit?: number,
  ): Promise<unknown> {
    return this.request('GET', '/operator/api/review-queue', undefined, {
      queue_date: queueDate,
      layer,
      offset,
      limit,
    });
  }

  async continueReviewQueue(payload: unknown): Promise<unknown> {
    return this.request('POST', '/operator/api/review-queue/continue', payload);
  }

  async getCustomers(limit?: number): Promise<unknown> {
    return this.request('GET', '/operator/api/customers', undefined, { limit });
  }

  async getCustomer(customerId: number): Promise<unknown> {
    return this.request('GET', `/operator/api/customers/${customerId}`);
  }

  async getCustomerTimeline(customerId: number): Promise<unknown> {
    return this.request('GET', `/operator/api/customers/${customerId}/timeline`);
  }

  async getContactAttempt(customerId: number): Promise<unknown> {
    return this.request('GET', `/operator/api/customers/${customerId}/contact-attempt`);
  }

  async prepareContactAttempt(customerId: number, payload: unknown): Promise<unknown> {
    return this.request('POST', `/operator/api/customers/${customerId}/contact-attempt/prepare`, payload);
  }

  async editContactAttempt(customerId: number, attemptId: number, payload: unknown): Promise<unknown> {
    return this.request('PUT', `/operator/api/customers/${customerId}/contact-attempt/${attemptId}/draft`, payload);
  }

  async approveContactAttempt(customerId: number, attemptId: number, payload: unknown): Promise<unknown> {
    return this.request('POST', `/operator/api/customers/${customerId}/contact-attempt/${attemptId}/approve`, payload);
  }

  async sendContactAttempt(customerId: number, attemptId: number, payload: unknown): Promise<unknown> {
    return this.request('POST', `/operator/api/customers/${customerId}/contact-attempt/${attemptId}/send`, payload);
  }

  async confirmContactNotSent(customerId: number, attemptId: number, payload: unknown): Promise<unknown> {
    return this.request('POST', `/operator/api/customers/${customerId}/contact-attempt/${attemptId}/confirm-not-sent`, payload);
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
      if (error instanceof HttpException) {
        throw error;
      }
      const status = this.backendStatus(error);
      if (status === 400) {
        throw new BadRequestException(this.safeError(400, 'invalid_request', '请求未被接受，请检查填写内容后重试'));
      }
      if (status === 401) {
        throw new UnauthorizedException(this.safeError(401, 'backend_unauthorized', '运营后端拒绝了服务端凭证，请联系管理员检查连接配置'));
      }
      if (status === 404) {
        throw new NotFoundException(this.safeError(404, 'resource_not_found', '请求的业务对象不存在或已被移除'));
      }
      if (status === 409) {
        throw new ConflictException(this.safeError(409, 'state_conflict', '联系状态已变化，请刷新后重新确认'));
      }
      if (status === 422) {
        throw new UnprocessableEntityException(this.safeError(422, 'validation_failed', '提交内容未通过校验，请补全必填信息后重试'));
      }
      if (status === 503) {
        throw new ServiceUnavailableException(this.safeError(503, 'backend_unavailable', '运营后端暂时无法处理请求，请稍后重试'));
      }
      throw this.unavailable('backend_unreachable', '运营后端暂时不可达，请稍后重试');
    }
  }

  private backendStatus(error: unknown): number | undefined {
    if (!error || typeof error !== 'object') return undefined;
    const status = (error as { response?: { status?: unknown } }).response?.status;
    return typeof status === 'number' ? status : undefined;
  }

  private safeError(statusCode: number, reason: string, message: string): Record<string, unknown> {
    return {
      statusCode,
      code: 'OPERATOR_BACKEND_REQUEST_FAILED',
      reason,
      message,
    };
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
