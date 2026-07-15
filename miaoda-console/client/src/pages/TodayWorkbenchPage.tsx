import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, CloudOff, RefreshCcw, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { getOperatorErrorReason, getOperatorWorkbench } from '../api/operator';
import { AttentionCard } from '../components/operator/AttentionCard';
import { LeadQueue } from '../components/operator/LeadQueue';
import { RunProgress } from '../components/operator/RunProgress';
import { SystemPulse } from '../components/operator/SystemPulse';
import { buildAttentionItems, formatRelativeTime, isWorkbenchEmpty } from '../features/operator/operator-view-model';


const errorCopy = {
  missing_base_url: ['尚未连接运营后端', '请在妙搭服务端配置 OPERATOR_API_BASE_URL。'],
  missing_token: ['尚未配置访问凭证', '请在妙搭服务端配置 OPERATOR_API_TOKEN，浏览器不会接触该凭证。'],
  backend_unreachable: ['运营后端暂时不可达', '页面仍可使用导航；请确认 FastAPI 的稳定公网地址与健康状态。'],
  unknown: ['工作台加载失败', '请稍后重试；如果持续失败，请查看妙搭服务端日志。'],
} as const;


export default function TodayWorkbenchPage() {
  const query = useQuery({
    queryKey: ['operator-workbench'],
    queryFn: getOperatorWorkbench,
    refetchInterval: 30_000,
    retry: 1,
  });
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const data = query.data;
  useEffect(() => {
    if (data?.lead_queue.length && !data.lead_queue.some((lead) => lead.id === selectedLeadId)) {
      setSelectedLeadId(data.lead_queue[0].id);
    }
  }, [data, selectedLeadId]);
  const selectedLead = data?.lead_queue.find((lead) => lead.id === selectedLeadId) ?? data?.lead_queue[0];
  const attentionItems = useMemo(() => data ? buildAttentionItems(data.attention) : [], [data]);

  return (
    <main className="mx-auto min-h-screen max-w-[1600px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">Operations Command Center</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">今日工作台</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">先看异常，再处理审核，最后关注运行中的任务。所有数字来自现有 FastAPI 与 PostgreSQL。</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden text-right sm:block">
            <p className="text-xs font-medium text-slate-500">最后更新</p>
            <p className="mt-1 text-sm font-semibold text-slate-800">{data ? formatRelativeTime(data.generated_at) : '等待连接'}</p>
          </div>
          <Button variant="outline" onClick={() => query.refetch()} disabled={query.isFetching}>
            <RefreshCcw className={query.isFetching ? 'animate-spin' : ''} />刷新
          </Button>
        </div>
      </div>

      {query.isLoading && <WorkbenchSkeleton />}
      {query.isError && (
        <>
          <DegradedState reason={getOperatorErrorReason(query.error)} onRetry={() => query.refetch()} />
          <OfflineStructurePreview />
        </>
      )}
      {data && (
        <>
          <div className="mt-6 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800">
            <ShieldCheck className="size-4" />服务端凭证隔离正常 · 页面每 30 秒自动刷新
          </div>
          <section className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {attentionItems.map((item) => <AttentionCard key={item.key} item={item} />)}
          </section>

          <section className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.85fr)]">
            <LeadQueue leads={data.lead_queue} selectedId={selectedLead?.id ?? null} onSelect={setSelectedLeadId} />
            <Card className="shadow-none">
              <CardHeader className="border-b border-slate-100 px-5 py-4">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-sky-700">Next Best Action</p>
                <CardTitle className="mt-2 text-lg leading-6 text-slate-950">{data.next_action.title}</CardTitle>
                <p className="text-sm leading-6 text-slate-600">{data.next_action.description}</p>
              </CardHeader>
              <CardContent className="p-5">
                {selectedLead ? (
                  <div>
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-medium text-slate-500">当前证据卡</p>
                        <p className="mt-1 text-base font-semibold text-slate-950">{selectedLead.display_name}</p>
                      </div>
                      <span className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white">{selectedLead.intent_score} 分</span>
                    </div>
                    <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <p className="text-xs font-semibold text-slate-500">证据摘要</p>
                      <p className="mt-2 text-sm leading-6 text-slate-700">{selectedLead.evidence_text || '暂无证据摘要。'}</p>
                    </div>
                    <div className="mt-4 rounded-xl border border-sky-100 bg-sky-50/70 p-4">
                      <p className="text-xs font-semibold text-sky-700">建议下一步</p>
                      <p className="mt-2 text-sm leading-6 text-slate-700">{selectedLead.recommended_next_step || '进入线索审核页补充信息并完成判断。'}</p>
                    </div>
                  </div>
                ) : (
                  <div className="py-8 text-center">
                    <p className="text-sm font-medium text-slate-700">暂无可展示的证据卡</p>
                    <p className="mt-1 text-xs text-slate-500">有待审核线索后，这里会显示关键证据与建议动作。</p>
                  </div>
                )}
                <Button asChild className="mt-5 w-full">
                  <Link to={data.next_action.target}>进入对应模块<ArrowRight /></Link>
                </Button>
              </CardContent>
            </Card>
          </section>

          <section className="mt-4 grid min-w-0 gap-4 xl:grid-cols-[minmax(300px,0.72fr)_minmax(0,1.28fr)]">
            <RunProgress runs={data.skill_runs} />
            <SystemPulse failures={data.task_failures} workers={data.workers} />
          </section>

          {isWorkbenchEmpty(data) && (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white px-5 py-4 text-sm text-slate-600">
              当前数据库没有需要处理的运营对象；页面没有使用演示数据替代真实结果。
            </div>
          )}
        </>
      )}
    </main>
  );
}


function DegradedState({ reason, onRetry }: { reason: keyof typeof errorCopy; onRetry: () => void }) {
  const [title, description] = errorCopy[reason];
  return (
    <Card className="mt-6 border-amber-200 bg-amber-50 shadow-none">
      <CardContent className="flex flex-col items-start gap-4 p-6 sm:flex-row sm:items-center">
        <span className="rounded-xl bg-white p-3 text-amber-700 shadow-sm"><CloudOff className="size-6" /></span>
        <div className="flex-1">
          <p className="font-semibold text-amber-950">{title}</p>
          <p className="mt-1 text-sm leading-6 text-amber-900/80">{description}</p>
        </div>
        <Button variant="outline" onClick={onRetry}><RefreshCcw />重试连接</Button>
      </CardContent>
    </Card>
  );
}


function WorkbenchSkeleton() {
  return (
    <div className="mt-6 space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-32" />)}
      </div>
      <div className="grid gap-4 xl:grid-cols-[1.55fr_0.85fr]">
        <Skeleton className="h-[430px]" />
        <Skeleton className="h-[430px]" />
      </div>
    </div>
  );
}


function OfflineStructurePreview() {
  return (
    <div className="mt-4 space-y-4" aria-label="操作台离线结构预览">
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {['失败任务', '待审核线索', '异常 Worker', '运行中任务'].map((label) => (
          <Card key={label} className="border-slate-200 bg-white shadow-none">
            <CardContent className="p-4">
              <p className="text-sm font-medium text-slate-500">{label}</p>
              <p className="mt-2 text-3xl font-semibold text-slate-300">—</p>
              <p className="mt-1 text-xs text-slate-400">连接后显示真实数据</p>
            </CardContent>
          </Card>
        ))}
      </section>
      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.85fr)]">
        <Card className="shadow-none">
          <CardHeader className="border-b border-slate-100 px-5 py-4">
            <CardTitle className="text-base text-slate-900">线索审核队列</CardTitle>
            <p className="text-xs text-slate-500">连接后按意向分数显示真实线索</p>
          </CardHeader>
          <CardContent className="space-y-3 p-5">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="rounded-lg border border-slate-100 p-4">
                <div className="h-3 w-28 rounded bg-slate-200" />
                <div className="mt-3 h-2 w-full rounded bg-slate-100" />
                <div className="mt-2 h-2 w-3/4 rounded bg-slate-100" />
              </div>
            ))}
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardHeader className="border-b border-slate-100 px-5 py-4">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-sky-700">Next Best Action</p>
            <CardTitle className="text-lg text-slate-900">连接后生成建议动作</CardTitle>
          </CardHeader>
          <CardContent className="p-5">
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-12 text-center text-sm text-slate-500">
              证据卡与建议动作将在后端恢复后自动加载
            </div>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
