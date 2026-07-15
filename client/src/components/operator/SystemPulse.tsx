import { AlertOctagon, Server } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import { formatRelativeTime, getWorkerHealthTone } from '../../features/operator/operator-view-model';
import type { TaskFailureItem, WorkerItem } from '../../types/operator';


export function SystemPulse({ failures, workers }: { failures: TaskFailureItem[]; workers: WorkerItem[] }) {
  return (
    <div className="grid min-w-0 gap-4 xl:grid-cols-2">
      <Card className="shadow-none">
        <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-slate-100 px-5 py-4">
          <CardTitle className="flex items-center gap-2 text-base text-slate-950">
            <AlertOctagon className="size-4 text-rose-600" />失败任务
          </CardTitle>
          <Badge variant={failures.length ? 'destructive' : 'outline'}>{failures.length}</Badge>
        </CardHeader>
        <CardContent className="p-5">
          {failures.length === 0 ? (
            <p className="py-5 text-center text-sm text-slate-500">最近没有失败任务。</p>
          ) : (
            <div className="space-y-4">
              {failures.slice(0, 4).map((failure) => (
                <div key={failure.id} className="rounded-lg border border-rose-100 bg-rose-50/60 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-slate-900">#{failure.id} · {failure.task_type}</p>
                    <span className="text-xs text-slate-500">{failure.attempt_count}/{failure.max_attempts}</span>
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs leading-5 text-rose-800">{failure.last_error || '未记录错误详情'}</p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      <Card className="shadow-none">
        <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-slate-100 px-5 py-4">
          <CardTitle className="flex items-center gap-2 text-base text-slate-950">
            <Server className="size-4 text-sky-600" />Worker 心跳
          </CardTitle>
          <Badge variant="outline" className="border-slate-200 text-slate-600">{workers.length}</Badge>
        </CardHeader>
        <CardContent className="p-5">
          {workers.length === 0 ? (
            <p className="py-5 text-center text-sm text-slate-500">尚未发现 Worker 心跳记录。</p>
          ) : (
            <div className="space-y-3">
              {workers.slice(0, 5).map((worker) => {
                const tone = getWorkerHealthTone(worker.health);
                return (
                  <div key={worker.worker_id} className="flex items-center justify-between gap-4 rounded-lg border border-slate-100 p-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">{worker.worker_id}</p>
                      <p className="mt-1 text-xs text-slate-500">{formatRelativeTime(worker.last_heartbeat_at)}</p>
                    </div>
                    <span className={cn(
                      'rounded-full px-2.5 py-1 text-xs font-semibold',
                      tone === 'danger' ? 'bg-rose-100 text-rose-700' : 'bg-emerald-100 text-emerald-700',
                    )}>
                      {worker.health === 'stale' ? '异常' : '正常'}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
