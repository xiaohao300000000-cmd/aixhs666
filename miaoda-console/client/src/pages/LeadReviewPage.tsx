import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Clock3, RefreshCcw, XCircle } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  continueOperatorReviewQueue,
  getOperatorLead,
  getOperatorReviewQueue,
  getOperatorRunCandidates,
  reviewOperatorLead,
} from '@/api/operator';
import { LeadEvidencePanel } from '@/components/operator/LeadEvidencePanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import {
  buildReviewLocation,
  buildReviewOutcome,
  getNextPendingQueueCandidateKey,
  leadActionRequiresReason,
  reuseIdempotencyKey,
  type StableRequestIdentity,
} from '@/features/operator/operator-view-model';
import type { LeadReviewAction, OperatorReviewQueueItem, ReviewLayer } from '@/types/operator';


const actions: Array<{ key: LeadReviewAction; label: string; icon: typeof CheckCircle2; tone: string }> = [
  { key: 'promote', label: '推进为客户', icon: CheckCircle2, tone: 'bg-emerald-600 hover:bg-emerald-700' },
  { key: 'defer', label: '暂缓判断', icon: Clock3, tone: 'bg-amber-500 hover:bg-amber-600' },
  { key: 'reject', label: '淘汰线索', icon: XCircle, tone: 'bg-rose-600 hover:bg-rose-700' },
];
const deferReasons = ['信息不足，等待新证据', '需求时间未到', '地区或课程待确认', '其他'];
const rejectReasons = ['明确广告或机构账号', '明确无关', '完全重复', '明确不符合 Campaign 硬条件', '人工确认无需求'];


function defaultDeferUntil(): string {
  const value = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000);
  value.setMinutes(value.getMinutes() - value.getTimezoneOffset());
  return value.toISOString().slice(0, 16);
}


export default function LeadReviewPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const queueDate = searchParams.get('queue_date') || undefined;
  const runId = Number(searchParams.get('run_id')) || null;
  const layer = (searchParams.get('layer') || '') as ReviewLayer | '';
  const currentKey = searchParams.get('candidate_key');
  const [reason, setReason] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [feedback, setFeedback] = useState('');
  const [deferUntil, setDeferUntil] = useState(defaultDeferUntil);
  const reviewIdentity = useRef<StableRequestIdentity | null>(null);
  const continueIdentity = useRef<StableRequestIdentity | null>(null);
  const queueQuery = useQuery({
    queryKey: ['operator-review-queue', queueDate, layer],
    queryFn: () => getOperatorReviewQueue({ queue_date: queueDate, layer: layer || undefined, limit: 200 }),
  });
  const runCandidatesQuery = useQuery({
    queryKey: ['operator-run-candidates', runId, layer],
    queryFn: () => getOperatorRunCandidates(runId!, layer || undefined),
    enabled: runId !== null,
  });
  const items = useMemo<OperatorReviewQueueItem[]>(() => {
    if (runId && runCandidatesQuery.data) {
      return runCandidatesQuery.data.items.map((candidate, index) => ({
        id: candidate.representative_screening_id,
        queue_date: queueQuery.data?.queue_date || queueDate || '',
        run_id: runId,
        candidate_key: candidate.candidate_key,
        lead_id: candidate.lead_id,
        screening_id: candidate.representative_screening_id,
        screening_ids: candidate.screening_ids,
        layer: candidate.layer,
        reason: candidate.reason,
        exclusion_sample_reason: candidate.hard_exclusion_reason,
        position: index + 1,
        slot_type: 'run_candidate',
        status: candidate.status,
        emergency: false,
        human_decision: null,
        miaoda_href: candidate.miaoda_href,
        next_action: candidate.next_action,
      }));
    }
    return queueQuery.data?.items ?? [];
  }, [queueDate, queueQuery.data, runCandidatesQuery.data, runId]);
  const selected = items.find((item) => item.candidate_key === currentKey) ?? items.find((item) => item.status === 'pending') ?? items[0] ?? null;
  const leadQuery = useQuery({
    queryKey: ['operator-lead', selected?.lead_id],
    queryFn: () => getOperatorLead(selected!.lead_id!),
    enabled: Boolean(selected?.lead_id),
    retry: false,
  });

  useEffect(() => {
    if (!selected || currentKey === selected.candidate_key) return;
    setSearchParams(buildParams(selected), { replace: true });
  }, [currentKey, selected, setSearchParams]);

  const buildParams = (item: OperatorReviewQueueItem) => {
    const path = buildReviewLocation({ queueDate: item.queue_date || queueDate, runId, layer: layer || null, candidateKey: item.candidate_key, position: item.position });
    return new URLSearchParams(path.split('?')[1] || '');
  };
  const selectItem = (item: OperatorReviewQueueItem) => {
    setSearchParams(buildParams(item));
    setFeedback('');
    reviewIdentity.current = null;
  };

  const reviewMutation = useMutation({
    mutationFn: ({ action, key }: { action: LeadReviewAction; key: string }) => {
      if (!selected?.lead_id) throw new Error('该候选缺少 lead_id，不能调用错误目标；请在技术详情中记录后交给管理员处理');
      if (selected.status !== 'pending') throw new Error('该候选已经处理，不能重复提交');
      if (leadActionRequiresReason(action) && !reason.trim()) throw new Error('暂缓或淘汰必须选择结构化原因');
      if (action === 'defer' && !deferUntil) throw new Error('暂缓判断必须设置恢复日期');
      return reviewOperatorLead(selected.lead_id, {
        action,
        reason: reason.trim() || undefined,
        owner_name: ownerName.trim() || undefined,
        reviewer_id: 'miaoda-operator',
        idempotency_key: key,
        defer_until: action === 'defer' ? new Date(deferUntil).toISOString() : undefined,
      });
    },
    onSuccess: async (result) => {
      const outcome = buildReviewOutcome({ progression: result.progression, baseStatus: null });
      setFeedback(`${outcome.summary}｜${outcome.boundary}`);
      setReason('');
      reviewIdentity.current = null;
      const nextKey = selected ? getNextPendingQueueCandidateKey(items, selected.candidate_key) : null;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['operator-review-queue'] }),
        queryClient.invalidateQueries({ queryKey: ['operator-run-candidates'] }),
        queryClient.invalidateQueries({ queryKey: ['operator-customers'] }),
        queryClient.invalidateQueries({ queryKey: ['operator-workbench'] }),
      ]);
      const nextItem = items.find((item) => item.candidate_key === nextKey);
      if (nextItem) setSearchParams(buildParams(nextItem));
    },
    onError: (error) => setFeedback(error instanceof Error ? error.message : '提交失败，可使用原幂等键重试'),
  });

  const submitReview = (action: LeadReviewAction) => {
    if (!selected) return;
    const signature = [action, selected.candidate_key, reason.trim(), action === 'defer' ? deferUntil : '', ownerName.trim()].join(':');
    const identity = reuseIdempotencyKey(reviewIdentity.current, signature, () => crypto.randomUUID());
    reviewIdentity.current = identity;
    reviewMutation.mutate({ action, key: identity.key });
  };

  const continueMutation = useMutation({
    mutationFn: ({ priorityOnly, key }: { priorityOnly: boolean; key: string }) => continueOperatorReviewQueue({
      queue_date: queueQuery.data?.queue_date || queueDate,
      additional: 20,
      priority_only: priorityOnly,
      idempotency_key: key,
    }),
    onSuccess: async (result) => {
      setFeedback(result.created ? `已追加 ${result.created} 条真实候选，原队列顺序保持不变。` : '没有可追加的候选，现有队列保持不变。');
      continueIdentity.current = null;
      await queryClient.invalidateQueries({ queryKey: ['operator-review-queue'] });
    },
    onError: (error) => setFeedback(error instanceof Error ? error.message : '扩展失败，可使用原幂等键重试'),
  });
  const continueQueue = (priorityOnly: boolean) => {
    const signature = `continue:${queueQuery.data?.queue_date || queueDate || 'today'}:${priorityOnly}:20`;
    const identity = reuseIdempotencyKey(continueIdentity.current, signature, () => crypto.randomUUID());
    continueIdentity.current = identity;
    continueMutation.mutate({ priorityOnly, key: identity.key });
  };
  const progress = queueQuery.data?.progress;
  const busy = reviewMutation.isPending || continueMutation.isPending;

  return (
    <main className="mx-auto max-w-[1650px] p-4 pb-32 md:p-8 md:pb-32">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">Continuous review</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">连续审核</h1><p className="mt-2 text-sm text-slate-500">稳定队列、完整证据、明确后果；处理后自动进入下一条。</p></div><Button variant="outline" onClick={() => queueQuery.refetch()} disabled={queueQuery.isFetching}><RefreshCcw className="size-4" />刷新</Button></header>
      {progress && <Card className="mb-5 shadow-none"><CardContent className="grid gap-4 p-4 sm:grid-cols-[auto_minmax(200px,1fr)_auto] sm:items-center"><div><p className="text-xs text-slate-500">今日审核</p><p className="text-xl font-semibold">{progress.completed} / {progress.target}</p></div><div><Progress value={progress.target ? progress.completed / progress.target * 100 : 0} /><p className="mt-2 text-xs text-slate-500">待处理 {progress.pending} · 质量控制 {progress.quality_control}</p></div><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => continueQueue(false)} disabled={busy}>继续审核 20 条</Button><Button variant="outline" onClick={() => continueQueue(true)} disabled={busy}>只看高优先级</Button></div></CardContent></Card>}
      {queueQuery.isError ? <StateCard title="审核队列暂时不可达" description="请确认运营后端在线后重试；页面不会使用演示候选。" /> : !items.length ? <StateCard title={runId ? '本次任务没有可显示候选' : '今日审核队列为空'} description={runId ? '返回任务结果查看分层与排除原因。' : '如已完成今日目标，可以选择继续审核 20 条。'} /> : progress?.pending === 0 && !runId ? <StateCard title="今日队列已全部完成" description="可以继续审核 20 条，或回到工作台处理客户行动。" /> : (
        <div className="grid min-w-0 gap-5 xl:grid-cols-[330px_minmax(0,1fr)_300px]">
          <QueueList items={items} selectedKey={selected?.candidate_key ?? null} onSelect={selectItem} />
          <div className="min-w-0">{selected?.lead_id ? leadQuery.isLoading ? <StateCard title="正在加载证据" description="请稍候。" /> : leadQuery.data ? <LeadEvidencePanel lead={leadQuery.data} /> : <StateCard title="线索详情加载失败" description="候选仍保留在队列中，请稍后重试。" /> : <StateCard title="该候选当前不可审核" description="缺少 lead_id，系统不会把动作提交到错误目标。请展开技术详情并交给管理员处理。" />}</div>
          <Card className="h-fit shadow-none"><CardHeader><CardTitle className="text-base">动作后果预览</CardTitle></CardHeader><CardContent className="space-y-3 text-sm leading-6 text-slate-600"><p><strong className="text-slate-900">推进为客户：</strong>建立或合并客户事实，进入客户中心与 Base CRM。</p><p><strong className="text-slate-900">暂缓判断：</strong>保留候选，按原因和恢复日期等待新证据。</p><p><strong className="text-slate-900">淘汰线索：</strong>记录结构化原因并保留审计。</p><div className="rounded-lg bg-amber-50 p-3 text-amber-900">公开回复草稿与真实发送尚未启用，将在 V19-05 开放。</div><details><summary className="cursor-pointer text-xs font-medium text-slate-500">技术详情</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-3 text-xs text-slate-200">{JSON.stringify(selected, null, 2)}</pre></details></CardContent></Card>
        </div>
      )}
      {selected && <Card className="fixed inset-x-3 bottom-3 z-20 border-slate-200 shadow-xl md:left-[calc(16rem+1rem)] md:right-4"><CardContent className="grid gap-3 p-4 lg:grid-cols-[180px_minmax(220px,1fr)_220px_auto] lg:items-center"><Input value={ownerName} onChange={(event) => setOwnerName(event.target.value)} placeholder="负责人（默认本人）" /><select value={reason} onChange={(event) => setReason(event.target.value)} className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm"><option value="">暂缓/淘汰请选择原因</option><optgroup label="暂缓原因">{deferReasons.map((item) => <option key={item}>{item}</option>)}</optgroup><optgroup label="淘汰原因">{rejectReasons.map((item) => <option key={item}>{item}</option>)}</optgroup></select><Input type="datetime-local" value={deferUntil} onChange={(event) => setDeferUntil(event.target.value)} aria-label="恢复日期" /><div className="flex flex-wrap gap-2">{actions.map(({ key, label, icon: Icon, tone }) => <Button key={key} className={tone} onClick={() => submitReview(key)} disabled={busy || !selected.lead_id || selected.status !== 'pending'}><Icon className="size-4" />{label}</Button>)}</div>{feedback && <div className="lg:col-span-4 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm font-medium text-sky-900">{feedback}{feedback.includes('客户 #') && <Link className="ml-2 underline" to={`/customers/${feedback.match(/客户 #(\d+)/)?.[1]}`}>打开客户详情</Link>}</div>}</CardContent></Card>}
    </main>
  );
}


function QueueList({ items, selectedKey, onSelect }: { items: OperatorReviewQueueItem[]; selectedKey: string | null; onSelect: (item: OperatorReviewQueueItem) => void }) {
  return <div className="max-h-[calc(100vh-245px)] space-y-2 overflow-y-auto pr-1">{items.map((item) => <button key={item.candidate_key} type="button" onClick={() => onSelect(item)} className={`w-full rounded-xl border bg-white p-4 text-left ${selectedKey === item.candidate_key ? 'border-sky-500 ring-2 ring-sky-100' : 'border-slate-200'}`}><div className="flex items-start justify-between gap-3"><div><p className="font-semibold">第 {item.position} 条</p><p className="mt-1 text-xs text-slate-500">{layerLabel(item.layer)} · {item.slot_type === 'quality_control' ? '质量控制' : '业务位'}</p></div><Badge variant={item.status === 'pending' ? 'secondary' : 'outline'}>{item.status === 'pending' ? '待审核' : '已完成'}</Badge></div><p className="mt-3 text-sm leading-6 text-slate-600">{item.reason || '暂无推荐原因'}</p>{!item.lead_id && <p className="mt-2 text-xs font-medium text-rose-600">缺少可审核客户对象</p>}</button>)}</div>;
}


function StateCard({ title, description }: { title: string; description: string }) { return <Card className="border-dashed shadow-none"><CardContent className="p-12 text-center"><p className="font-semibold text-slate-800">{title}</p><p className="mt-2 text-sm text-slate-500">{description}</p></CardContent></Card>; }
function layerLabel(layer: string) { return ({ priority_review: '高优先级', standard_review: '普通审核', uncertain_review: '不确定 / QC', automatic_exclusion: '排除抽检' } as Record<string, string>)[layer] ?? layer; }
