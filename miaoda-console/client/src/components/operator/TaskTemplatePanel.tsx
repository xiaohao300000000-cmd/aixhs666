import { Database, ShieldCheck } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { SkillTemplate } from '@/types/operator';


export function TaskTemplatePanel({ template }: { template: SkillTemplate }) {
  const businessName = template.key === 'screen_historical_leads' ? '扩大潜在线索池' : template.name;
  return <Card className="border-sky-200 bg-gradient-to-br from-white to-sky-50 shadow-none"><CardHeader><div className="flex items-center justify-between"><Badge>已发布 · v{template.version}</Badge><ShieldCheck className="size-5 text-emerald-600" /></div><CardTitle className="mt-3">{businessName}</CardTitle><p className="text-sm leading-6 text-slate-600">{template.description}</p></CardHeader><CardContent><div className="flex items-center gap-2 text-sm text-slate-600"><Database className="size-4" />只读取 PostgreSQL 历史数据，不访问外部平台，不自动联系客户。</div><details className="mt-4 text-xs text-slate-500"><summary className="cursor-pointer font-medium">查看处理阶段</summary><div className="mt-3 flex flex-wrap gap-2">{template.stages.map((stage) => <Badge key={stage} variant="outline">{stage}</Badge>)}</div></details></CardContent></Card>;
}
