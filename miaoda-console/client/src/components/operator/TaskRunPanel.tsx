import { AlertTriangle, CheckCircle2, Clock3 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { getRunStatusLabel } from '@/features/operator/operator-view-model';
import type { OperatorSkillRun } from '@/types/operator';


export function TaskRunPanel({ run }: { run: OperatorSkillRun }) {
  const candidateCount = Number(run.preview.candidate_count ?? 0);
  return <div className="space-y-4"><Card className="shadow-none"><CardHeader className="border-b border-slate-100"><div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-700">Run #{run.id}</p><CardTitle className="mt-2">{getRunStatusLabel(run.status)}</CardTitle></div><Badge variant={run.status === 'failed' ? 'destructive' : 'secondary'}>{run.status}</Badge></div></CardHeader><CardContent className="space-y-5 p-5"><div><div className="mb-2 flex justify-between text-sm"><span>{run.stage || '等待下一步'}</span><span>{run.progress.percent}%</span></div><Progress value={run.progress.percent} /></div>{Object.keys(run.preview).length > 0 && <div className="grid gap-3 sm:grid-cols-3"><Metric label="候选数量" value={candidateCount} /><Metric label="处理上限" value={Number(run.preview.limit ?? 0)} /><Metric label="外部平台" value="不访问" /></div>}{run.error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"><AlertTriangle className="mr-2 inline size-4" />{run.error.message}</div>}{Object.keys(run.result).length > 0 && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4"><div className="flex items-center gap-2 font-semibold text-emerald-800"><CheckCircle2 className="size-4" />运行结果</div><pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs leading-6 text-emerald-950">{JSON.stringify(run.result, null, 2)}</pre></div>}</CardContent></Card><Card className="shadow-none"><CardHeader><CardTitle className="text-base">状态时间线</CardTitle></CardHeader><CardContent className="space-y-3">{[...run.events].reverse().map((event) => <div key={`${event.sequence}-${event.type}`} className="flex gap-3 border-l-2 border-slate-200 pl-4"><Clock3 className="mt-0.5 size-4 shrink-0 text-slate-400" /><div><p className="text-sm font-medium">{event.type} <span className="font-normal text-slate-400">{event.status}</span></p><p className="mt-1 text-xs text-slate-500">{event.created_at ? new Date(event.created_at).toLocaleString('zh-CN') : '时间未知'}</p></div></div>)}</CardContent></Card></div>;
}

function Metric({ label, value }: { label: string; value: string | number }) { return <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold">{value}</p></div>; }

