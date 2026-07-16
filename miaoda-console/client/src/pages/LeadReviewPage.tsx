import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Clock3, RefreshCcw, XCircle } from 'lucide-react';

import { getOperatorLeads, reviewOperatorLead } from '@/api/operator';
import { LeadEvidencePanel } from '@/components/operator/LeadEvidencePanel';
import { LeadReviewQueue } from '@/components/operator/LeadReviewQueue';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { getNextLeadId, leadActionRequiresReason } from '@/features/operator/operator-view-model';
import type { LeadReviewAction } from '@/types/operator';


const actions: Array<{ key: LeadReviewAction; label: string; icon: typeof CheckCircle2; tone: string }> = [
  { key: 'promote', label: '推进为客户', icon: CheckCircle2, tone: 'bg-emerald-600 hover:bg-emerald-700' },
  { key: 'defer', label: '暂缓判断', icon: Clock3, tone: 'bg-amber-500 hover:bg-amber-600' },
  { key: 'reject', label: '淘汰线索', icon: XCircle, tone: 'bg-rose-600 hover:bg-rose-700' },
];


function defaultDeferUntil(): string {
  const value = new Date(Date.now() + 3 * 24 * 60 * 60 * 1000);
  value.setMinutes(value.getMinutes() - value.getTimezoneOffset());
  return value.toISOString().slice(0, 16);
}


function progressionLabel(stage: string): string {
  if (stage === 'awaiting_first_contact') return '待首次联系';
  if (stage === 'deferred') return '已暂缓';
  if (stage === 'invalid') return '已淘汰';
  return stage;
}


function nextActionLabel(action: string): string {
  if (action === 'prepare_public_reply') return '准备公开回复';
  if (action === 'wait_for_reactivation') return '等待重新提醒';
  if (action === 'none') return '无需继续处理';
  return action;
}


export default function LeadReviewPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('pending');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [reason, setReason] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [feedback, setFeedback] = useState('');
  const [deferUntil, setDeferUntil] = useState(defaultDeferUntil);
  const query = useQuery({ queryKey: ['operator-leads', filter], queryFn: () => getOperatorLeads(filter) });
  const items = query.data?.items ?? [];
  const selected = useMemo(() => items.find((item) => item.id === selectedId) ?? items[0] ?? null, [items, selectedId]);

  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
  }, [selected, selectedId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!selected || !items.length || ['INPUT', 'TEXTAREA', 'SELECT'].includes((event.target as HTMLElement)?.tagName)) return;
      const index = items.findIndex((item) => item.id === selected.id);
      if (event.key.toLowerCase() === 'j' || event.key === 'ArrowDown') setSelectedId(items[Math.min(index + 1, items.length - 1)]?.id ?? selected.id);
      if (event.key.toLowerCase() === 'k' || event.key === 'ArrowUp') setSelectedId(items[Math.max(index - 1, 0)]?.id ?? selected.id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [items, selected]);

  const mutation = useMutation({
    mutationFn: ({ action, idempotencyKey }: { action: LeadReviewAction; idempotencyKey: string }) => {
      if (!selected) throw new Error('请先选择线索');
      if (leadActionRequiresReason(action) && !reason.trim()) throw new Error('该判断必须填写原因');
      if (action === 'defer' && !deferUntil) throw new Error('暂缓判断必须设置重新提醒时间');
      return reviewOperatorLead(selected.id, {
        action,
        reason: reason.trim() || undefined,
        owner_name: ownerName.trim() || undefined,
        reviewer_id: 'miaoda-operator',
        idempotency_key: idempotencyKey,
        defer_until: action === 'defer' ? new Date(deferUntil).toISOString() : undefined,
      });
    },
    onSuccess: async (result) => {
      const nextId = getNextLeadId(items, result.lead.id);
      setFeedback(`已处理客户 #${result.progression.customer_id}｜当前阶段：${progressionLabel(result.progression.customer_stage)}｜下一步：${nextActionLabel(result.progression.next_action)}`);
      setReason('');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['operator-leads'] }),
        queryClient.invalidateQueries({ queryKey: ['operator-workbench'] }),
      ]);
      setSelectedId(nextId);
    },
    onError: (error) => setFeedback(error instanceof Error ? error.message : '提交失败'),
  });

  return (
    <main className="mx-auto max-w-[1600px] p-4 md:p-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">Review Queue</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">线索审核</h1><p className="mt-2 text-sm text-slate-500">左侧选线索，右侧看完整证据；处理后自动进入下一条，J/K 可切换。</p></div>
        <div className="flex items-center gap-2">
          <select value={filter} onChange={(event) => setFilter(event.target.value)} className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm">
            <option value="pending">待审核</option><option value="all">全部</option><option value="watch">观察</option><option value="information_insufficient">信息不足</option><option value="qualified">有效</option><option value="ignored">无效</option>
          </select>
          <Button variant="outline" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCcw className="size-4" />刷新</Button>
        </div>
      </div>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Card className="shadow-none"><CardContent className="p-4"><p className="text-xs text-slate-500">当前队列</p><p className="mt-1 text-2xl font-semibold">{query.data?.total ?? '—'}</p></CardContent></Card>
        <Card className="shadow-none"><CardContent className="p-4"><p className="text-xs text-slate-500">待审核</p><p className="mt-1 text-2xl font-semibold text-amber-600">{query.data?.pending_total ?? '—'}</p></CardContent></Card>
        <Card className="shadow-none"><CardContent className="p-4"><p className="text-xs text-slate-500">预计处理时间</p><p className="mt-1 text-2xl font-semibold">{query.data ? `${Math.ceil(query.data.pending_total * 1.5)} 分钟` : '—'}</p></CardContent></Card>
      </div>
      {query.isError ? <div className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">加载失败，请确认运营后端在线。</div> : (
        <div className="grid gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
          <div className="max-h-[calc(100vh-230px)] overflow-y-auto pr-1"><LeadReviewQueue items={items} selectedId={selected?.id ?? null} onSelect={setSelectedId} /></div>
          {selected ? <div className="space-y-4"><LeadEvidencePanel lead={selected} />
            <Card className="sticky bottom-4 border-slate-200 shadow-lg"><CardContent className="space-y-4 p-5">
              <div className="grid gap-3 md:grid-cols-3"><Input value={ownerName} onChange={(event) => setOwnerName(event.target.value)} placeholder="负责人（默认本人）" /><Textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="暂缓或淘汰时必须填写原因" className="min-h-10" /><Input type="datetime-local" value={deferUntil} onChange={(event) => setDeferUntil(event.target.value)} aria-label="重新提醒时间" /></div>
              <div className="flex flex-wrap gap-2">{actions.map(({ key, label, icon: Icon, tone }) => <Button key={key} className={tone} onClick={() => mutation.mutate({ action: key, idempotencyKey: crypto.randomUUID() })} disabled={mutation.isPending}><Icon className="size-4" />{label}</Button>)}</div>
              {feedback && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800">{feedback}</div>}
            </CardContent></Card>
          </div> : <div className="rounded-xl border border-dashed border-slate-300 p-16 text-center text-slate-500">队列已清空</div>}
        </div>
      )}
    </main>
  );
}
