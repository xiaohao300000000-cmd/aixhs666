import { AlertTriangle, ChevronRight, Clock3, Database } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { buildRunReportView, getRunStatusLabel } from '@/features/operator/operator-view-model';
import type { OperatorRunCandidates, OperatorRunReport, OperatorSkillRun } from '@/types/operator';


export function TaskRunPanel({
  run,
  report,
  reportMissing,
  candidates,
}: {
  run: OperatorSkillRun;
  report?: OperatorRunReport;
  reportMissing?: boolean;
  candidates?: OperatorRunCandidates;
}) {
  const model = report ? buildRunReportView(report) : null;
  const candidateCount = Number(run.preview.candidate_count ?? 0);
  return (
    <div className="space-y-4">
      <Card className="shadow-none">
        <CardHeader className="border-b border-slate-100">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-700">任务 #{run.id}</p><CardTitle className="mt-2">{model?.conclusion || getRunStatusLabel(run.status)}</CardTitle></div>
            <Badge variant={run.status === 'failed' ? 'destructive' : 'secondary'}>{getRunStatusLabel(run.status)}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-5 p-5">
          <div><div className="mb-2 flex justify-between text-sm"><span>{run.stage ? '任务正在推进' : '等待下一步'}</span><span>{run.progress.percent}%</span></div><Progress value={run.progress.percent} /></div>
          {Object.keys(run.preview).length > 0 && <div className="grid gap-3 sm:grid-cols-3"><Metric label="预计分析" value={candidateCount} /><Metric label="处理上限" value={Number(run.preview.limit ?? run.parameters.limit ?? 0)} /><Metric label="是否联系客户" value="不会" /></div>}
          {run.error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700"><AlertTriangle className="mr-2 inline size-4" />任务未完成，请根据下方技术详情联系管理员。</div>}
          {model && (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {model.funnel.map((item) => item.href ? <Link key={item.key} to={item.href} className="rounded-xl border border-slate-200 p-4 transition hover:border-sky-400 hover:bg-sky-50"><p className="text-xs text-slate-500">{item.label}</p><p className="mt-1 text-2xl font-semibold">{item.value}</p></Link> : <Metric key={item.key} label={item.label} value={item.value} />)}
              </div>
              <div className="rounded-xl border border-slate-200 p-4">
                <p className="font-semibold text-slate-900">结果去了哪里</p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {model.destinations.map((item) => <div key={item.key} className="flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-sm"><Database className="mt-0.5 size-4 text-sky-600" /><div><p className="font-medium">{destinationLabel(item.key)} · {destinationStatus(item.status)}</p><p className="mt-1 text-xs leading-5 text-slate-500">{item.detail || '状态由现有 Operator API 提供'}</p></div></div>)}
                </div>
              </div>
              <Button asChild><Link to={`/leads?run_id=${run.id}`}>审核本次候选<ChevronRight /></Link></Button>
            </>
          )}
          {reportMissing && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">该历史任务尚未生成业务报告。原始成功状态不会替代业务结论。</div>}
          {candidates && <div className="rounded-xl border border-slate-200 p-4"><p className="font-semibold">候选明细 · {layerLabel(candidates.layer)}</p>{candidates.items.length ? <div className="mt-3 space-y-2">{candidates.items.map((candidate) => <Link key={candidate.candidate_key} to={`/leads?run_id=${run.id}&layer=${candidate.layer}&candidate_key=${encodeURIComponent(candidate.candidate_key)}`} className="block rounded-lg bg-slate-50 p-3 text-sm hover:bg-sky-50"><div className="flex justify-between gap-3"><span className="font-medium">{candidate.reason}</span><span className="text-slate-500">置信度 {candidate.confidence ?? '未知'}</span></div><p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{candidate.evidence[0] || '暂无证据摘要'}</p></Link>)}</div> : <p className="mt-2 text-sm text-slate-500">该分层没有候选。</p>}</div>}
        </CardContent>
      </Card>
      <details className="rounded-xl border border-slate-200 bg-white p-5">
        <summary className="cursor-pointer text-sm font-semibold text-slate-700">技术详情</summary>
        <div className="mt-4 space-y-4">
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-4 text-xs leading-6 text-slate-200">{JSON.stringify({ result: run.result, preview: run.preview }, null, 2)}</pre>
          <div className="space-y-3">{[...run.events].reverse().map((event) => <div key={`${event.sequence}-${event.type}`} className="flex gap-3 border-l-2 border-slate-200 pl-4"><Clock3 className="mt-0.5 size-4 shrink-0 text-slate-400" /><div><p className="text-sm font-medium">{event.type} <span className="font-normal text-slate-400">{event.status}</span></p><p className="mt-1 text-xs text-slate-500">{event.created_at ? new Date(event.created_at).toLocaleString('zh-CN') : '时间未知'}</p></div></div>)}</div>
        </div>
      </details>
    </div>
  );
}


function Metric({ label, value }: { label: string; value: string | number }) { return <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold">{value}</p></div>; }
function destinationLabel(key: string) { return ({ postgresql: '业务事实', miaoda: '妙搭审核', base: 'Base CRM', feishu: '飞书提醒' } as Record<string, string>)[key] ?? key; }
function destinationStatus(status: string) { return ({ persisted: '已保留', ready: '可审核', synced: '已同步', summary_ready: '摘要已准备', not_written: '未写入', partial_failure: '部分失败', not_requested: '未请求' } as Record<string, string>)[status] ?? status; }
function layerLabel(layer: string | null) { return ({ priority_review: '高优先级', standard_review: '普通审核', uncertain_review: '不确定审核', automatic_exclusion: '自动排除抽检' } as Record<string, string>)[layer ?? ''] ?? '全部'; }
