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
