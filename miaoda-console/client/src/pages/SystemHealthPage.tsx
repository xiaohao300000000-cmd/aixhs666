import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, CheckCircle2, RefreshCcw, Server, Unplug } from 'lucide-react';
import { Link } from 'react-router-dom';

import { getOperatorWorkbench } from '@/api/operator';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { buildSystemHealthModel, formatRelativeTime } from '@/features/operator/operator-view-model';


export default function SystemHealthPage() {
  const query = useQuery({ queryKey: ['operator-workbench'], queryFn: getOperatorWorkbench, refetchInterval: 30_000, retry: 1 });
  const model = query.data ? buildSystemHealthModel(query.data) : null;
  return (
    <main className="mx-auto max-w-[1450px] p-4 md:p-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">System health</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">系统健康</h1><p className="mt-2 text-sm text-slate-500">工程信息集中在这里；默认只展示安全摘要，不暴露 token、内部 URL 或完整堆栈。</p></div><Button variant="outline" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCcw className={query.isFetching ? 'animate-spin' : ''} />刷新</Button></header>
      {query.isLoading && <State icon={Activity} title="正在读取系统状态" description="请稍候。" />}
      {query.isError && !model && <State icon={Unplug} title="Operator 后端不可达" description="没有可证明的最新状态；请稍后重试或联系管理员检查网关。" danger />}
      {model && <div className="space-y-5">
        <Card className="shadow-none"><CardContent className="grid gap-4 p-5 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-center"><span className="rounded-xl bg-emerald-50 p-3 text-emerald-700"><Server className="size-6" /></span><div><p className="font-semibold">{model.connection.label}</p><p className="mt-1 text-sm text-slate-500">最后成功：{formatRelativeTime(model.connection.lastSuccessAt)}</p></div><span className="text-sm font-medium text-emerald-700">已连接</span></CardContent></Card>
        <section className="grid gap-5 lg:grid-cols-2">
          <Card className="shadow-none"><CardHeader><CardTitle>Worker 状态</CardTitle></CardHeader><CardContent className="space-y-3">{model.workers.length ? model.workers.map((worker) => <div key={worker.id} className="rounded-xl border border-slate-200 p-4"><div className="flex items-center justify-between gap-3"><p className="font-medium">{worker.label}</p><span className={worker.label === '需要恢复' ? 'text-sm font-medium text-rose-700' : 'text-sm font-medium text-emerald-700'}>{worker.currentTask}</span></div><p className="mt-2 text-xs text-slate-500">最后心跳：{formatRelativeTime(worker.lastHeartbeatAt)} · 完成 {worker.completed} · 失败 {worker.failed}</p></div>) : <p className="text-sm text-slate-500">现有 API 没有返回 Worker 事实。</p>}</CardContent></Card>
          <Card className="shadow-none"><CardHeader><CardTitle>外围集成状态</CardTitle></CardHeader><CardContent className="space-y-3">{model.integrations.map((item) => <div key={item.key} className="flex items-center justify-between rounded-xl border border-slate-200 p-4 text-sm"><span className="font-medium">{item.label}</span><span className="text-slate-500">{item.status}</span></div>)}<p className="text-xs leading-5 text-slate-400">当前 Operator workbench 没有提供 Base/飞书健康探针，因此不会显示“正常”或“已连接”。</p></CardContent></Card>
        </section>
        <FailureSection title="阻塞业务的异常" items={model.blockingFailures} empty="没有可证明会阻塞当前业务动作的失败。" />
        <FailureSection title="非阻塞异常" items={model.nonBlockingFailures} empty="没有非阻塞后台失败。" />
        <div className="flex flex-wrap gap-2"><Button asChild variant="outline"><Link to="/tasks">回到业务任务</Link></Button><Button asChild variant="outline"><Link to="/leads">回到连续审核</Link></Button><Button asChild variant="outline"><Link to="/">回到今日工作台</Link></Button></div>
      </div>}
    </main>
  );
}


function FailureSection({ title, items, empty }: { title: string; items: Array<{ id: number; title: string; summary: string; attempts: string; updatedAt: string | null; href: string }>; empty: string }) {
  return <Card className="shadow-none"><CardHeader><CardTitle className="flex items-center gap-2"><AlertTriangle className="size-5 text-amber-600" />{title}</CardTitle></CardHeader><CardContent>{items.length ? <div className="space-y-3">{items.map((item) => <div key={item.id} className="grid gap-3 rounded-xl border border-slate-200 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"><div><p className="font-medium">{item.title}</p><p className="mt-1 text-sm leading-6 text-slate-500">{item.summary}</p><p className="mt-1 text-xs text-slate-400">尝试 {item.attempts} · {formatRelativeTime(item.updatedAt)}</p></div><Button asChild variant="outline" size="sm"><Link to={item.href}>查看对应动作</Link></Button></div>)}</div> : <div className="flex items-center gap-2 text-sm text-emerald-700"><CheckCircle2 className="size-4" />{empty}</div>}</CardContent></Card>;
}


function State({ icon: Icon, title, description, danger = false }: { icon: typeof Activity; title: string; description: string; danger?: boolean }) { return <Card className={`${danger ? 'border-rose-200 bg-rose-50' : 'border-dashed'} shadow-none`}><CardContent className="p-14 text-center"><Icon className={`mx-auto size-8 ${danger ? 'text-rose-500' : 'text-slate-400'}`} /><p className="mt-4 font-semibold">{title}</p><p className="mt-2 text-sm text-slate-500">{description}</p></CardContent></Card>; }
