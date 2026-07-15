import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeftRight, CheckCircle2, Eye, RefreshCcw, UserRoundCheck, XCircle } from 'lucide-react';

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
  { key: 'valid', label: '确认有效', icon: CheckCircle2, tone: 'bg-emerald-600 hover:bg-emerald-700' },
  { key: 'watch', label: '暂时观察', icon: Eye, tone: 'bg-amber-500 hover:bg-amber-600' },
  { key: 'invalid', label: '判定无效', icon: XCircle, tone: 'bg-rose-600 hover:bg-rose-700' },
  { key: 'needs_information', label: '补充信息', icon: ArrowLeftRight, tone: 'bg-slate-700 hover:bg-slate-800' },
  { key: 'follow_up', label: '进入跟进', icon: UserRoundCheck, tone: 'bg-sky-600 hover:bg-sky-700' },
];


export default function LeadReviewPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('pending');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [reason, setReason] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [feedback, setFeedback] = useState('');
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
    mutationFn: ({ action }: { action: LeadReviewAction }) => {
      if (!selected) throw new Error('请先选择线索');
      if (leadActionRequiresReason(action) && !reason.trim()) throw new Error('该判断必须填写原因');
      return reviewOperatorLead(selected.id, { action, reason: reason.trim() || undefined, owner_name: ownerName.trim() || undefined });
    },
    onSuccess: async (updated, variables) => {
      const nextId = getNextLeadId(items, updated.id);
      setFeedback(`${updated.display_name} 已完成：${actions.find((item) => item.key === variables.action)?.label}`);
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
              <div className="grid gap-3 md:grid-cols-2"><Input value={ownerName} onChange={(event) => setOwnerName(event.target.value)} placeholder="负责人（进入跟进时建议填写）" /><Textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="无效、观察、补充信息必须填写标准原因" className="min-h-10" /></div>
              <div className="flex flex-wrap gap-2">{actions.map(({ key, label, icon: Icon, tone }) => <Button key={key} className={tone} onClick={() => mutation.mutate({ action: key })} disabled={mutation.isPending}><Icon className="size-4" />{label}</Button>)}</div>
              {feedback && <p className="text-sm text-slate-600">{feedback}</p>}
            </CardContent></Card>
          </div> : <div className="rounded-xl border border-dashed border-slate-300 p-16 text-center text-slate-500">队列已清空</div>}
        </div>
      )}
    </main>
  );
}

