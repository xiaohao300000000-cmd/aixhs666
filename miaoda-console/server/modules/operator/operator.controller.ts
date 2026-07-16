import { Body, Controller, Get, Param, ParseIntPipe, Post, Query } from '@nestjs/common';

import { OperatorService } from './operator.service';


@Controller('api/operator')
export class OperatorController {
  constructor(private readonly operatorService: OperatorService) {}

  @Get('workbench')
  getWorkbench(): Promise<unknown> {
    return this.operatorService.getWorkbench();
  }

  @Get('leads')
  getLeads(@Query('status_filter') statusFilter?: string, @Query('limit') limit?: string): Promise<unknown> {
    return this.operatorService.getLeads(statusFilter, limit ? Number(limit) : undefined);
  }

  @Get('leads/:leadId')
  getLead(@Param('leadId', ParseIntPipe) leadId: number): Promise<unknown> {
    return this.operatorService.getLead(leadId);
  }

  @Post('leads/:leadId/review')
  reviewLead(@Param('leadId', ParseIntPipe) leadId: number, @Body() payload: unknown): Promise<unknown> {
    return this.operatorService.reviewLead(leadId, payload);
  }

  @Get('tasks')
  getTasks(@Query('limit') limit?: string): Promise<unknown> {
    return this.operatorService.getTasks(limit ? Number(limit) : undefined);
  }

  @Get('tasks/runs/:runId')
  getRun(@Param('runId', ParseIntPipe) runId: number): Promise<unknown> {
    return this.operatorService.getRun(runId);
  }

  @Get('tasks/runs/:runId/report')
  getRunReport(@Param('runId', ParseIntPipe) runId: number): Promise<unknown> {
    return this.operatorService.getRunReport(runId);
  }

  @Get('tasks/runs/:runId/candidates')
  getRunCandidates(
    @Param('runId', ParseIntPipe) runId: number,
    @Query('layer') layer?: string,
  ): Promise<unknown> {
    return this.operatorService.getRunCandidates(runId, layer);
  }

  @Get('review-queue')
  getReviewQueue(
    @Query('queue_date') queueDate?: string,
    @Query('layer') layer?: string,
    @Query('offset') offset?: string,
    @Query('limit') limit?: string,
  ): Promise<unknown> {
    return this.operatorService.getReviewQueue(
      queueDate,
      layer,
      offset ? Number(offset) : undefined,
      limit ? Number(limit) : undefined,
    );
  }

  @Post('review-queue/continue')
  continueReviewQueue(@Body() payload: unknown): Promise<unknown> {
    return this.operatorService.continueReviewQueue(payload);
  }

  @Get('customers')
  getCustomers(@Query('limit') limit?: string): Promise<unknown> {
    return this.operatorService.getCustomers(limit ? Number(limit) : undefined);
  }

  @Get('customers/:customerId')
  getCustomer(@Param('customerId', ParseIntPipe) customerId: number): Promise<unknown> {
    return this.operatorService.getCustomer(customerId);
  }

  @Get('customers/:customerId/timeline')
  getCustomerTimeline(@Param('customerId', ParseIntPipe) customerId: number): Promise<unknown> {
    return this.operatorService.getCustomerTimeline(customerId);
  }

  @Post('tasks/runs')
  createRun(@Body() payload: unknown): Promise<unknown> {
    return this.operatorService.createRun(payload);
  }

  @Post('tasks/runs/:runId/:action')
  runAction(
    @Param('runId', ParseIntPipe) runId: number,
    @Param('action') action: string,
    @Body() payload: unknown,
  ): Promise<unknown> {
    return this.operatorService.runAction(runId, action, payload);
  }
}
