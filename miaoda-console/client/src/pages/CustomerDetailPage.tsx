import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Bot, CalendarClock, Database, ExternalLink, RefreshCcw } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';

import { getOperatorCustomer, getOperatorCustomerTimeline, getOperatorErrorReason } from '@/api/operator';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { buildCustomerSummaryView, buildCustomerTimelineView, sanitizeOperatorErrorSummary } from '@/features/operator/operator-view-model';


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
          <div className="space-y-5"><Card className="shadow-none"><CardHeader><CardTitle className="flex items-center gap-2"><CalendarClock className="size-5 text-sky-600" />客户时间线</CardTitle></CardHeader><CardContent className="space-y-4">{timelineQuery.isError ? <p className="text-sm text-rose-600">时间线暂时不可达。</p> : !timeline.length ? <p className="text-sm text-slate-500">该客户还没有时间线事实。</p> : timeline.map((item) => <div key={item.id} className="border-l-2 border-sky-200 pl-4"><p className="font-medium">{item.title}</p><p className="mt-1 text-sm leading-6 text-slate-500">{item.description}</p><p className="mt-1 text-xs text-slate-400">{new Date(item.occurredAt).toLocaleString('zh-CN')}</p><details className="mt-2"><summary className="cursor-pointer text-xs text-slate-400">技术详情</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-3 text-xs text-slate-200">{JSON.stringify(item.raw, null, 2)}</pre></details></div>)}</CardContent></Card><Card className="shadow-none"><CardHeader><CardTitle>同步与去向</CardTitle></CardHeader><CardContent className="space-y-3"><p className={`text-sm font-medium ${customer.sync_status === 'failed' ? 'text-rose-700' : customer.sync_status === 'synced' ? 'text-emerald-700' : 'text-amber-700'}`}>{summary.syncLabel}</p>{customer.sync_error && <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">同步失败摘要：{sanitizeOperatorErrorSummary(customer.sync_error)}</p>}{customer.base_record_url ? <Button asChild variant="outline"><a href={customer.base_record_url} target="_blank" rel="noreferrer"><Database />打开对应 Base 记录<ExternalLink /></a></Button> : <p className="text-sm text-slate-500">当前没有 Base mapping；不会显示虚假的 Base 入口。</p>}<p className="text-xs text-slate-400">妙搭稳定地址：/customers/{customer.customer_id}</p></CardContent></Card><Card className="border-amber-200 bg-amber-50 shadow-none"><CardContent className="p-4 text-sm leading-6 text-amber-900">联系草稿、真实发送状态和飞书回复提醒尚无 V19-04 可证明事实，将在 V19-05 / V19-06 开放。</CardContent></Card></div>
        </section>
      </div>}
    </main>
  );
}


function State({ title, description }: { title: string; description: string }) { return <Card className="border-dashed shadow-none"><CardContent className="p-14 text-center"><p className="font-semibold">{title}</p><p className="mt-2 text-sm text-slate-500">{description}</p></CardContent></Card>; }
function Metric({ label, value }: { label: string; value: string | number }) { return <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 font-semibold">{value}</p></div>; }
