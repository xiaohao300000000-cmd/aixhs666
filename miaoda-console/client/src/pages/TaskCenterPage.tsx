import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Eye, Play, RefreshCcw, RotateCcw, Square } from 'lucide-react';

import { cancelOperatorRun, copyOperatorRun, createOperatorRun, getOperatorTasks, previewOperatorRun, queueOperatorRun, retryOperatorRun } from '@/api/operator';
import { TaskRunPanel } from '@/components/operator/TaskRunPanel';
import { TaskTemplatePanel } from '@/components/operator/TaskTemplatePanel';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { getRunActions, getRunStatusLabel } from '@/features/operator/operator-view-model';
import type { OperatorSkillRun, SkillRunParameters } from '@/types/operator';


export default function TaskCenterPage() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ['operator-tasks'], queryFn: getOperatorTasks, refetchInterval: 5000 });
  const template = query.data?.templates[0];
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [draftRun, setDraftRun] = useState<OperatorSkillRun | null>(null);
  const [feedback, setFeedback] = useState('');
  const [parameters, setParameters] = useState<SkillRunParameters>({ data_range: 'all', source_types: 'content_and_comment', limit: 50, campaign_id: '' });
  const runs = query.data?.runs ?? [];
  const selectedRun = useMemo(() => draftRun && draftRun.id === selectedRunId ? draftRun : runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? draftRun, [draftRun, runs, selectedRunId]);

  useEffect(() => { if (template) setParameters((current) => current.campaign_id ? current : template.defaults); }, [template]);
  useEffect(() => { if (selectedRun && selectedRun.id !== selectedRunId) setSelectedRunId(selectedRun.id); }, [selectedRun, selectedRunId]);

  const mutation = useMutation({
    mutationFn: async (action: string) => {
      if (!template) throw new Error('当前没有可用模板');
      if (action === 'create') return createOperatorRun(template.key);
      if (!selectedRun) throw new Error('请先创建或选择任务');
      if (action === 'preview') return previewOperatorRun(selectedRun.id, parameters);
      if (action === 'queue') return queueOperatorRun(selectedRun.id);
      if (action === 'cancel') return cancelOperatorRun(selectedRun.id);
      if (action === 'retry') return retryOperatorRun(selectedRun.id);
      if (action === 'copy') return copyOperatorRun(selectedRun.id);
      throw new Error('未知动作');
    },
    onSuccess: async (run, action) => {
      setDraftRun(run);
      setSelectedRunId(run.id);
      setFeedback(`Run #${run.id}：${getRunStatusLabel(run.status)}`);
      if (action === 'copy') setParameters({ ...template!.defaults, ...run.parameters });
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['operator-tasks'] }), queryClient.invalidateQueries({ queryKey: ['operator-workbench'] })]);
    },
    onError: (error) => setFeedback(error instanceof Error ? error.message : '操作失败'),
  });

  const availableActions = selectedRun ? getRunActions(selectedRun) : [];
  return <main className="mx-auto max-w-[1600px] p-4 md:p-8"><div className="mb-6 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-700">Skill Runtime</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">任务中心</h1><p className="mt-2 text-sm text-slate-500">从安全模板创建任务，预览影响范围后再确认执行；状态与结果持续回流。</p></div><Button variant="outline" onClick={() => query.refetch()}><RefreshCcw className="size-4" />刷新</Button></div>{query.isError ? <div className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">任务中心加载失败，请确认运营后端在线。</div> : <div className="grid gap-5 xl:grid-cols-[320px_380px_minmax(0,1fr)]"><div className="space-y-4">{template && <TaskTemplatePanel template={template} />}<Button className="w-full" onClick={() => mutation.mutate('create')} disabled={mutation.isPending || !template}>创建任务草稿</Button><Card className="shadow-none"><CardHeader><CardTitle className="text-base">运行历史</CardTitle></CardHeader><CardContent className="space-y-2">{runs.map((run) => <button key={run.id} type="button" onClick={() => { setSelectedRunId(run.id); setDraftRun(null); setParameters({ ...template!.defaults, ...run.parameters }); }} className={`w-full rounded-lg border p-3 text-left ${selectedRun?.id === run.id ? 'border-sky-500 bg-sky-50' : 'border-slate-200'}`}><div className="flex justify-between"><span className="font-medium">Run #{run.id}</span><span className="text-xs text-slate-500">{getRunStatusLabel(run.status)}</span></div><p className="mt-1 text-xs text-slate-400">{run.updated_at ? new Date(run.updated_at).toLocaleString('zh-CN') : '暂无时间'}</p></button>)}</CardContent></Card></div><Card className="h-fit shadow-none"><CardHeader><CardTitle className="text-base">参数与运行预览</CardTitle></CardHeader><CardContent className="space-y-4"><label className="block text-sm font-medium">数据范围<select value={parameters.data_range} onChange={(event) => setParameters({ ...parameters, data_range: event.target.value as SkillRunParameters['data_range'] })} className="mt-2 h-10 w-full rounded-md border border-slate-200 px-3"><option value="all">全部历史</option><option value="last_30_days">最近 30 天</option><option value="last_90_days">最近 90 天</option></select></label><label className="block text-sm font-medium">来源类型<select value={parameters.source_types} onChange={(event) => setParameters({ ...parameters, source_types: event.target.value as SkillRunParameters['source_types'] })} className="mt-2 h-10 w-full rounded-md border border-slate-200 px-3"><option value="content_and_comment">内容 + 评论</option><option value="content_only">仅内容</option><option value="comment_only">仅评论</option></select></label><label className="block text-sm font-medium">Campaign<select value={parameters.campaign_id} onChange={(event) => setParameters({ ...parameters, campaign_id: event.target.value })} className="mt-2 h-10 w-full rounded-md border border-slate-200 px-3">{query.data?.campaigns.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.name} · {campaign.location_summary}</option>)}</select></label><label className="block text-sm font-medium">处理上限<Input type="number" min={1} max={500} value={parameters.limit} onChange={(event) => setParameters({ ...parameters, limit: Number(event.target.value) })} className="mt-2" /></label><div className="rounded-xl bg-emerald-50 p-4 text-sm leading-6 text-emerald-900">安全说明：此模板只处理数据库历史数据；预览不会调用模型，确认执行后才进入 Worker 队列。</div><div className="flex flex-wrap gap-2">{selectedRun && availableActions.includes('preview') && <Button onClick={() => mutation.mutate('preview')}><Eye className="size-4" />生成预览</Button>}{selectedRun && availableActions.includes('queue') && <Button className="bg-emerald-600 hover:bg-emerald-700" onClick={() => mutation.mutate('queue')}><Play className="size-4" />确认执行</Button>}{selectedRun && availableActions.includes('cancel') && <Button variant="outline" onClick={() => mutation.mutate('cancel')}><Square className="size-4" />取消</Button>}{selectedRun && availableActions.includes('retry') && <Button onClick={() => mutation.mutate('retry')}><RotateCcw className="size-4" />重试</Button>}{selectedRun && availableActions.includes('copy') && <Button variant="outline" onClick={() => mutation.mutate('copy')}><Copy className="size-4" />复制任务</Button>}</div>{feedback && <p className="text-sm text-slate-600">{feedback}</p>}</CardContent></Card><div>{selectedRun ? <TaskRunPanel run={selectedRun} /> : <div className="rounded-xl border border-dashed border-slate-300 p-16 text-center text-slate-500">创建任务后在这里查看预览、进度与结果</div>}</div></div>}</main>;
}

