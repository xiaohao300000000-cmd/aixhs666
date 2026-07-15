import { Activity } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import type { SkillRunItem } from '../../types/operator';


export function RunProgress({ runs }: { runs: SkillRunItem[] }) {
  return (
    <Card className="shadow-none">
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-slate-100 px-5 py-4">
        <CardTitle className="flex items-center gap-2 text-base text-slate-950">
          <Activity className="size-4 text-sky-600" />运行中任务
        </CardTitle>
        <Badge variant="outline" className="border-slate-200 text-slate-600">{runs.length}</Badge>
      </CardHeader>
      <CardContent className="space-y-5 p-5">
        {runs.length === 0 ? (
          <p className="py-5 text-center text-sm text-slate-500">当前没有运行中的 Skill Run。</p>
        ) : runs.map((run) => (
          <div key={run.id}>
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-900">#{run.id} · {run.skill_key}</p>
                <p className="mt-1 text-xs text-slate-500">{run.current_stage || '准备执行'}</p>
              </div>
              <span className="text-sm font-semibold text-slate-800">{run.progress_percent}%</span>
            </div>
            <Progress value={run.progress_percent} className="mt-3 h-2" />
            <p className="mt-2 text-xs text-slate-500">{run.progress_current} / {run.progress_total}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
