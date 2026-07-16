import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Database, RefreshCcw, UsersRound } from 'lucide-react';
import { Link } from 'react-router-dom';

import { getOperatorCustomers } from '@/api/operator';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { buildCustomerSummaryView, formatRelativeTime } from '@/features/operator/operator-view-model';


export default function CustomersPage() {
  const query = useQuery({ queryKey: ['operator-customers'], queryFn: () => getOperatorCustomers(200) });
  const items = query.data?.items.map(buildCustomerSummaryView) ?? [];
  return (
    <main className="mx-auto max-w-[1500px] p-4 md:p-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">Customer CRM</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">客户中心</h1><p className="mt-2 text-sm text-slate-500">这里只显示 PostgreSQL 中真实的 qualified 客户，并提供对应 Base 记录入口。</p></div><Button variant="outline" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCcw className="size-4" />刷新</Button></header>
      {query.isLoading && <State title="正在加载客户" description="从 Operator API 读取正式客户。" />}
      {query.isError && <State title="客户中心暂时不可达" description="请确认运营后端在线；页面不会展示演示客户。" danger />}
      {query.data && !items.length && <State title="当前没有正式客户" description="候选推进为客户后会出现在这里。" />}
      {!!items.length && <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{items.map((item) => <Card key={item.id} className="shadow-none"><CardHeader><div className="flex items-start justify-between gap-3"><div><p className="text-xs text-slate-500">客户 #{item.id}</p><CardTitle className="mt-2 text-lg">{item.name}</CardTitle></div><span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">{item.stageLabel}</span></div></CardHeader><CardContent className="space-y-4"><div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">下一步</p><p className="mt-1 text-sm font-medium leading-6">{item.nextStep}</p></div><div className={`flex items-center gap-2 text-sm ${item.syncTone === 'danger' ? 'text-rose-700' : item.syncTone === 'success' ? 'text-emerald-700' : 'text-amber-700'}`}><Database className="size-4" />{item.syncLabel}</div><p className="text-xs text-slate-400">更新于 {formatRelativeTime(item.updatedAt)}</p><div className="flex flex-wrap gap-2"><Button asChild><Link to={item.miaodaHref}>查看客户<ArrowRight /></Link></Button>{item.baseAvailable && item.baseHref && <Button asChild variant="outline"><a href={item.baseHref} target="_blank" rel="noreferrer"><Database />打开 Base 记录</a></Button>}</div></CardContent></Card>)}</div>}
    </main>
  );
}


function State({ title, description, danger = false }: { title: string; description: string; danger?: boolean }) { return <Card className={`${danger ? 'border-rose-200 bg-rose-50' : 'border-dashed'} shadow-none`}><CardContent className="p-14 text-center"><UsersRound className={`mx-auto size-8 ${danger ? 'text-rose-500' : 'text-slate-400'}`} /><p className="mt-4 font-semibold">{title}</p><p className="mt-2 text-sm text-slate-500">{description}</p></CardContent></Card>; }
