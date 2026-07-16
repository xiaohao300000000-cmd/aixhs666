import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  CheckCircle2,
  CloudOff,
  Database,
  RefreshCcw,
  ShieldCheck,
  UsersRound,
} from 'lucide-react';
import { Link } from 'react-router-dom';

import {
  getOperatorCustomers,
  getOperatorErrorReason,
  getOperatorReviewQueue,
  getOperatorRunReport,
  getOperatorTasks,
  getOperatorWorkbench,
} from '../api/operator';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { buildTodayActionModel, formatRelativeTime } from '../features/operator/operator-view-model';


const errorCopy = {
  missing_base_url: ['尚未连接运营后端', '请联系管理员配置稳定的运营后端地址。'],
  missing_token: ['尚未配置访问凭证', '请联系管理员检查妙搭服务端凭证。浏览器不会接触该凭证。'],
  backend_unreachable: ['运营后端暂时不可达', '请稍后重试；系统恢复前不会显示演示数字。'],
  backend_unavailable: ['运营后端暂时无法处理请求', '服务可能正在恢复，请稍后刷新。'],
  backend_unauthorized: ['服务端连接凭证失效', '请联系管理员检查运营网关凭证。'],
  invalid_request: ['工作台请求未被接受', '请刷新页面；若持续出现请到系统健康页查看。'],
  resource_not_found: ['业务数据尚未准备好', '今日队列或最近报告可能尚未生成。'],
  validation_failed: ['工作台查询条件无效', '请刷新页面恢复默认查询。'],
  unknown: ['工作台加载失败', '请稍后重试；若持续失败请查看系统健康。'],
} as const;


export default function TodayWorkbenchPage() {
  const workbenchQuery = useQuery({ queryKey: ['operator-workbench'], queryFn: getOperatorWorkbench, refetchInterval: 30_000, retry: 1 });
  const queueQuery = useQuery({ queryKey: ['operator-review-queue', 'today'], queryFn: () => getOperatorReviewQueue({ limit: 200 }), refetchInterval: 30_000, retry: 1 });
  const customersQuery = useQuery({ queryKey: ['operator-customers'], queryFn: () => getOperatorCustomers(200), refetchInterval: 30_000, retry: 1 });
  const tasksQuery = useQuery({ queryKey: ['operator-tasks'], queryFn: getOperatorTasks, refetchInterval: 30_000, retry: 1 });
  const recentRunId = tasksQuery.data?.runs.find((run) => run.status === 'succeeded')?.id ?? null;
  const reportQuery = useQuery({
    queryKey: ['operator-run-report', recentRunId],
    queryFn: () => getOperatorRunReport(recentRunId!),
    enabled: recentRunId !== null,
    retry: false,
  });
  const model = useMemo(() => {
    if (!workbenchQuery.data || !queueQuery.data || !customersQuery.data) return null;
    return buildTodayActionModel({
      workbench: workbenchQuery.data,
      reviewQueue: queueQuery.data,
      customers: customersQuery.data,
      recentReport: reportQuery.data ?? null,
    });
  }, [customersQuery.data, queueQuery.data, reportQuery.data, workbenchQuery.data]);
  const queries = [workbenchQuery, queueQuery, customersQuery, tasksQuery];
  const firstError = queries.find((query) => query.isError)?.error;
  const loading = queries.some((query) => query.isLoading);
  const fetching = queries.some((query) => query.isFetching) || reportQuery.isFetching;
  const refresh = async () => {
    await Promise.all(queries.map((query) => query.refetch()));
    if (recentRunId !== null) await reportQuery.refetch();
  };

  return (
    <main className="mx-auto min-h-screen max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">Today&apos;s actions</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">今天做什么</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">先完成最影响业务的动作；工程细节统一下沉到系统健康。</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right text-xs text-slate-500">
            <p>每 30 秒自动刷新 · 当前{fetching ? '刷新中' : '已同步'}</p>
            <p className="mt-1 font-medium text-slate-700">最后更新：{workbenchQuery.data ? formatRelativeTime(workbenchQuery.data.generated_at) : '等待连接'}</p>
          </div>
          <Button variant="outline" onClick={refresh} disabled={fetching}><RefreshCcw className={fetching ? 'animate-spin' : ''} />手动刷新</Button>
        </div>
      </header>

      {loading && <WorkbenchSkeleton />}
      {firstError && <DegradedState reason={getOperatorErrorReason(firstError)} onRetry={refresh} />}
      {model && workbenchQuery.data && queueQuery.data && customersQuery.data && (
        <div className="mt-6 space-y-5">
          <Card className="overflow-hidden border-sky-200 bg-gradient-to-br from-slate-950 to-sky-950 text-white shadow-none">
            <CardContent className="grid gap-5 p-6 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-300">今天最重要的事</p>
                <h2 className="mt-3 text-2xl font-semibold">{model.primaryAction.title}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">{model.primaryAction.description}</p>
              </div>
              <Button asChild size="lg" className="bg-white text-slate-950 hover:bg-sky-50">
                <Link to={model.primaryAction.href}>现在处理<ArrowRight /></Link>
              </Button>
            </CardContent>
          </Card>

          <section className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <Card className="shadow-none">
              <CardHeader><CardTitle className="flex items-center gap-2"><CheckCircle2 className="size-5 text-emerald-600" />今日审核</CardTitle></CardHeader>
              <CardContent className="space-y-5">
                <div className="flex items-end justify-between gap-4"><p className="text-3xl font-semibold">{model.reviewProgress.completed} / {model.reviewProgress.target}</p><p className="text-sm text-slate-500">待处理 {model.reviewProgress.pending} · 质检位 {model.reviewProgress.qualityControl}</p></div>
                <Progress value={model.reviewProgress.target ? model.reviewProgress.completed / model.reviewProgress.target * 100 : 0} />
                <div className="grid gap-3 sm:grid-cols-3">
                  <ReviewLink label="高优先级" value={model.reviewLayers.priority} layer="priority_review" queueDate={queueQuery.data.queue_date} />
                  <ReviewLink label="普通审核" value={model.reviewLayers.standard} layer="standard_review" queueDate={queueQuery.data.queue_date} />
                  <ReviewLink label="不确定 / QC" value={model.reviewLayers.uncertain} layer="uncertain_review" queueDate={queueQuery.data.queue_date} />
                </div>
              </CardContent>
            </Card>
            <Card className="shadow-none">
              <CardHeader><CardTitle className="flex items-center gap-2"><UsersRound className="size-5 text-sky-600" />客户状态</CardTitle></CardHeader>
              <CardContent className="grid grid-cols-2 gap-3">
                <Metric label="客户总数" value={model.customerMetrics.total} />
                <Metric label="待首次联系" value={model.customerMetrics.awaitingFirstContact} />
                <Metric label="已联系待回复" value={model.customerMetrics.contactedWaitingReply} />
                <Metric label="到期跟进" value="尚未接入" muted />
                <Button asChild variant="outline" className="col-span-2"><Link to="/customers"><Database />打开客户中心与 Base CRM</Link></Button>
              </CardContent>
            </Card>
          </section>

          <section className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
            <Card className="shadow-none">
              <CardHeader><CardTitle>最近完成任务</CardTitle></CardHeader>
              <CardContent>
                {model.recentReport ? <div><p className="text-base font-medium leading-7 text-slate-900">{model.recentReport.conclusion}</p><Button asChild className="mt-4"><Link to={`/tasks?run_id=${model.recentReport.runId}`}>查看结果<ArrowRight /></Link></Button></div> : <p className="text-sm leading-6 text-slate-500">{recentRunId ? '该历史任务尚未生成业务报告。' : '暂无已完成任务。'}</p>}
              </CardContent>
            </Card>
            <Card className="shadow-none">
              <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-5 text-emerald-600" />系统与后续能力</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {model.unavailableCapabilities.map((item) => <div key={item.key} className="flex items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2 text-sm"><span>{item.label}</span><span className="text-xs font-medium text-slate-500">尚未启用 · {item.note}</span></div>)}
                <div className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-3 text-sm"><span>{workbenchQuery.data.attention.failed_tasks || workbenchQuery.data.attention.stale_workers ? '存在需要查看的系统异常' : '未发现阻塞业务的系统异常'}</span><Button asChild variant="ghost" size="sm"><Link to="/system-health">查看详情</Link></Button></div>
              </CardContent>
            </Card>
          </section>
        </div>
      )}
    </main>
  );
}


function ReviewLink({ label, value, layer, queueDate }: { label: string; value: number; layer: string; queueDate: string }) {
  return <Link to={`/leads?queue_date=${queueDate}&layer=${layer}`} className="rounded-xl border border-slate-200 p-4 transition hover:border-sky-400 hover:bg-sky-50"><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-2xl font-semibold">{value}</p></Link>;
}


function Metric({ label, value, muted = false }: { label: string; value: number | string; muted?: boolean }) {
  return <div className="rounded-xl bg-slate-50 p-4"><p className="text-xs text-slate-500">{label}</p><p className={`mt-1 font-semibold ${muted ? 'text-sm text-slate-500' : 'text-2xl text-slate-950'}`}>{value}</p></div>;
}


function DegradedState({ reason, onRetry }: { reason: keyof typeof errorCopy; onRetry: () => void }) {
  const [title, description] = errorCopy[reason];
  return <Card className="mt-6 border-amber-200 bg-amber-50 shadow-none"><CardContent className="flex flex-col items-start gap-4 p-6 sm:flex-row sm:items-center"><span className="rounded-xl bg-white p-3 text-amber-700"><CloudOff className="size-6" /></span><div className="flex-1"><p className="font-semibold text-amber-950">{title}</p><p className="mt-1 text-sm leading-6 text-amber-900/80">{description}</p></div><Button variant="outline" onClick={onRetry}><RefreshCcw />重试连接</Button></CardContent></Card>;
}


function WorkbenchSkeleton() {
  return <div className="mt-6 space-y-4"><Skeleton className="h-44" /><div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-64" /><Skeleton className="h-64" /></div></div>;
}
