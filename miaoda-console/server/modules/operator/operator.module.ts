import { HttpModule } from '@nestjs/axios';
import { Module } from '@nestjs/common';

import { OperatorController } from './operator.controller';
import { OperatorService } from './operator.service';


@Module({
  imports: [HttpModule.register({ timeout: 8_000, maxRedirects: 2 })],
  controllers: [OperatorController],
  providers: [OperatorService],
})
export class OperatorModule {}
