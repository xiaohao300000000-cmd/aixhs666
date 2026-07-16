import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Bot, CalendarClock, Database, ExternalLink, RefreshCcw } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { approveOperatorContactAttempt, confirmOperatorContactNotSent, editOperatorContactAttempt, getOperatorContactAttempt, getOperatorCustomer, getOperatorCustomerTimeline, getOperatorErrorReason, prepareOperatorContactAttempt, sendOperatorContactAttempt } from '@/api/operator';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { buildContactAttemptView, buildCustomerSummaryView, buildCustomerTimelineView, sanitizeOperatorErrorSummary } from '@/features/operator/operator-view-model';
import type { OperatorContactAttempt } from '@/types/operator';


export default function CustomerDetailPage() {
  const customerId = Number(useParams().id);
  const detailQuery = useQuery({ queryKey: ['operator-customer', customerId], queryFn: () => getOperatorCustomer(customerId), enabled: Number.isFinite(customerId), retry: false });
  const timelineQuery = useQuery({ queryKey: ['operator-customer-timeline', customerId], queryFn: () => getOperatorCustomerTimeline(customerId), enabled: Number.isFinite(customerId), retry: false });
  const customer = detailQuery.data;
  const summary = customer ? buildCustomerSummaryView(customer) : null;
  const timeline = timelineQuery.data ? buildCustomerTimelineView(timelineQuery.data) : [];
  const notFound = detailQuery.isError && getOperatorErrorReason(detailQuery.error) === 'resource_not_found';
  const refresh = async () => Promise.all([detailQuery.refetch(), timelineQuery.refetch()]);
  return (
    <main className="mx-auto max-w-[1450px] p-4 md:p-8">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><Button asChild variant="ghost"><Link to="/customers"><ArrowLeft />返回客户中心</Link></Button><Button variant="outline" onClick={refresh} disabled={detailQuery.isFetching || timelineQuery.isFetching}><RefreshCcw className="size-4" />刷新</Button></div>
      {detailQuery.isLoading && <State title="正在加载客户详情" description="请稍候。" />}
      {notFound && <State title="客户不存在" description="该客户可能不是正式客户，或已被移除。" />}
      {detailQuery.isError && !notFound && <State title="客户详情暂时不可达" description="请确认运营后端在线后重试。" />}
      {customer && summary && <div className="space-y-5">
        <Card className="shadow-none"><CardContent className="grid gap-5 p-6 lg:grid-cols-[minmax(0,1fr)_auto]"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-700">客户 #{customer.customer_id}</p><h1 className="mt-2 text-3xl font-semibold">{customer.customer_name}</h1><p className="mt-2 text-sm text-slate-500">{customer.region || '地区未知'} · {customer.product || customer.demand_type || '需求待确认'} · 意向 {customer.intent_score}</p><div className="mt-4 flex flex-wrap gap-2"><Badge>{summary.stageLabel}</Badge>{customer.customer_tags.map((tag) => <Badge key={tag} variant="outline">{tag}</Badge>)}</div></div><div className="min-w-[260px] rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">当前行动</p><p className="mt-2 font-semibold leading-6">{summary.nextStep}</p><p className="mt-3 text-xs text-slate-500">下次跟进：{customer.next_followup_at ? new Date(customer.next_followup_at).toLocaleString('zh-CN') : '尚未安排'}</p><p className="mt-1 text-xs text-slate-500">最近联系：{customer.last_contact_at ? new Date(customer.last_contact_at).toLocaleString('zh-CN') : '尚无真实联系记录'}</p></div></CardContent></Card>
        <section className="grid gap-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(340px,0.95fr)]">
          <div className="space-y-5"><Card className="shadow-none"><CardHeader><CardTitle>需求与证据</CardTitle></CardHeader><CardContent className="space-y-3">{customer.evidence.length ? customer.evidence.map((item) => <div key={item.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-xs text-slate-400">{item.source_entity_type} #{item.source_entity_id}</p><p className="mt-2 text-sm leading-7 text-slate-700">{item.text}</p></div>) : <p className="text-sm text-slate-500">该客户暂无可展示证据。</p>}</CardContent></Card><Card className="shadow-none"><CardHeader><CardTitle className="flex items-center gap-2"><Bot className="size-5 text-sky-600" />AI 判断</CardTitle></CardHeader><CardContent>{customer.ai_judgment ? <div className="grid gap-3 sm:grid-cols-3"><Metric label="判断状态" value={customer.ai_judgment.review_status} /><Metric label="置信度" value={customer.ai_judgment.confidence ?? '未知'} /><Metric label="Campaign 判断" value={customer.ai_judgment.qualification_decision || '未提供'} /></div> : <p className="text-sm text-slate-500">没有可用的 AI 判断事实。</p>}</CardContent></Card></div>
          <div className="space-y-5"><ContactAttemptCard customerId={customer.customer_id} /><Card className="shadow-none"><CardHeader><CardTitle className="flex items-center gap-2"><CalendarClock className="size-5 text-sky-600" />客户时间线</CardTitle></CardHeader><CardContent className="space-y-4">{timelineQuery.isError ? <p className="text-sm text-rose-600">时间线暂时不可达。</p> : !timeline.length ? <p className="text-sm text-slate-500">该客户还没有时间线事实。</p> : timeline.map((item) => <div key={item.id} className="border-l-2 border-sky-200 pl-4"><p className="font-medium">{item.title}</p><p className="mt-1 text-sm leading-6 text-slate-500">{item.description}</p><p className="mt-1 text-xs text-slate-400">{new Date(item.occurredAt).toLocaleString('zh-CN')}</p><details className="mt-2"><summary className="cursor-pointer text-xs text-slate-400">技术详情</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-3 text-xs text-slate-200">{JSON.stringify(item.raw, null, 2)}</pre></details></div>)}</CardContent></Card><Card className="shadow-none"><CardHeader><CardTitle>同步与去向</CardTitle></CardHeader><CardContent className="space-y-3"><p className={`text-sm font-medium ${customer.sync_status === 'failed' ? 'text-rose-700' : customer.sync_status === 'synced' ? 'text-emerald-700' : 'text-amber-700'}`}>{summary.syncLabel}</p>{customer.sync_error && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">同步失败摘要：{sanitizeOperatorErrorSummary(customer.sync_error)}</p>}{customer.base_record_url ? <Button asChild variant="outline"><a href={customer.base_record_url} target="_blank" rel="noreferrer"><Database />打开对应 Base 记录<ExternalLink /></a></Button> : <p className="text-sm text-slate-500">当前没有 Base mapping；不会显示虚假的 Base 入口。</p>}<p className="text-xs text-slate-400">妙搭稳定地址：/customers/{customer.customer_id}</p></CardContent></Card></div>
        </section>
      </div>}
    </main>
  );
}


function State({ title, description }: { title: string; description: string }) { return <Card className="border-dashed shadow-none"><CardContent className="p-14 text-center"><p className="font-semibold">{title}</p><p className="mt-2 text-sm text-slate-500">{description}</p></CardContent></Card>; }
function Metric({ label, value }: { label: string; value: string | number }) { return <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></div>; }

type ContactCommand = { signature: string; execute: (key: string) => Promise<OperatorContactAttempt> };

function ContactAttemptCard({ customerId }: { customerId: number }) {
  const queryClient = useQueryClient();
  const keys = useRef<Record<string, string>>({});
  const [draft, setDraft] = useState('');
  const [sendConfirmed, setSendConfirmed] = useState(false);
  const [recoveryReason, setRecoveryReason] = useState('');
  const [feedback, setFeedback] = useState('');
  const query = useQuery({ queryKey: ['operator-contact-attempt', customerId], queryFn: () => getOperatorContactAttempt(customerId), retry: false });
  const attempt = query.data;
  const view = attempt ? buildContactAttemptView(attempt) : null;
  const missing = query.isError && getOperatorErrorReason(query.error) === 'resource_not_found';
  useEffect(() => { if (attempt) setDraft(attempt.draft_text); }, [attempt]);
  const mutation = useMutation({
    mutationFn: ({ signature, execute }: ContactCommand) => {
      keys.current[signature] ||= crypto.randomUUID();
      return execute(keys.current[signature]);
    },
    onSuccess: async (result, variables) => {
      delete keys.current[variables.signature];
      setDraft(result.draft_text);
      setSendConfirmed(false);
      setRecoveryReason('');
      setFeedback('联系状态已持久化。');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['operator-contact-attempt', customerId] }),
        queryClient.invalidateQueries({ queryKey: ['operator-customer', customerId] }),
        queryClient.invalidateQueries({ queryKey: ['operator-customer-timeline', customerId] }),
      ]);
    },
    onError: () => setFeedback('操作未完成；若状态已变化请先刷新，直接重试会沿用同一幂等键。'),
  });
  const run = (command: ContactCommand) => mutation.mutate(command);
  return <Card className="shadow-none"><CardHeader><CardTitle>公开回复联系</CardTitle></CardHeader><CardContent className="space-y-4">
    {query.isLoading && <p className="text-sm text-slate-500">正在加载持久联系事实…</p>}
    {missing && <div className="space-y-3"><p className="text-sm text-slate-600">尚无持久草稿。仅会为已有的合格公开评论目标排队生成，不会在本地虚构文本。</p><Button onClick={() => run({ signature: `prepare:${customerId}`, execute: (key) => prepareOperatorContactAttempt(customerId, key) })} disabled={mutation.isPending}>生成公开回复草稿</Button></div>}
    {query.isError && !missing && <p className="text-sm text-rose-700">联系事实暂时不可达，请检查运营后端后重试。</p>}
    {attempt && view && <>
      <div className="flex flex-wrap items-center gap-2"><Badge>{view.statusLabel}</Badge><Badge variant="outline">版本 {attempt.draft_revision}</Badge><Badge variant="outline">小红书公开回复</Badge></div>
      <div className="rounded-xl bg-slate-50 p-3 text-sm"><p>目标评论：{attempt.target.comment_id}</p>{attempt.target.url ? <a className="mt-1 block text-sky-700 underline" href={attempt.target.url} target="_blank" rel="noreferrer">打开公开目标</a> : <p className="mt-1 text-amber-700">目标链接缺失，禁止发送。</p>}</div>
      <Textarea value={draft} onChange={(event) => setDraft(event.target.value)} disabled={!view.canEdit || mutation.isPending} rows={5} aria-label="公开回复草稿" />
      {view.canEdit && draft.trim() !== attempt.draft_text && <Button variant="outline" onClick={() => run({ signature: `edit:${attempt.attempt_id}:${attempt.draft_revision}:${draft.trim()}`, execute: (key) => editOperatorContactAttempt(customerId, attempt.attempt_id, draft, key) })} disabled={!draft.trim() || mutation.isPending}>保存修改（将生成新版本）</Button>}
      {view.canApprove && draft === attempt.draft_text && <Button onClick={() => run({ signature: `approve:${attempt.attempt_id}:${attempt.draft_revision}`, execute: (key) => approveOperatorContactAttempt(customerId, attempt, key) })} disabled={mutation.isPending}>确认话术（不会发送）</Button>}
      {view.canSend && <div className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4"><p className="font-semibold text-amber-950">最终发送确认</p><p className="text-sm leading-6 text-amber-900">将向评论 {attempt.target.comment_id} 公开发送版本 {attempt.draft_revision} 的完整文本：</p><blockquote className="border-l-2 border-amber-400 pl-3 text-sm">{attempt.draft_text}</blockquote><label className="flex items-start gap-2 text-sm"><Checkbox checked={sendConfirmed} onCheckedChange={(value) => setSendConfirmed(value === true)} />我已逐字核对目标、渠道和最终文本，确认创建唯一发送任务。</label><Button variant="destructive" disabled={!sendConfirmed || mutation.isPending || !attempt.target.url} onClick={() => run({ signature: `send:${attempt.attempt_id}:${attempt.draft_revision}`, execute: (key) => sendOperatorContactAttempt(customerId, attempt, key) })}>发送公开回复</Button></div>}
      {view.canRecover && <div className="space-y-3 rounded-xl border border-rose-300 bg-rose-50 p-4"><p className="text-sm font-semibold text-rose-900">结果未知：禁止自动重试</p><Textarea value={recoveryReason} onChange={(event) => setRecoveryReason(event.target.value)} placeholder="填写人工打开目标页面后的核验依据" /><Button variant="outline" disabled={!recoveryReason.trim() || mutation.isPending} onClick={() => run({ signature: `not-sent:${attempt.attempt_id}:${recoveryReason.trim()}`, execute: (key) => confirmOperatorContactNotSent(customerId, attempt.attempt_id, recoveryReason, key) })}>确认平台未发送</Button></div>}
      <p className="text-xs text-slate-500">私信联系：尚未接入。本页面不会把公开回复误称为私信。</p>
    </>}
    {feedback && <p className="text-sm text-slate-600">{feedback}</p>}
  </CardContent></Card>;
}
