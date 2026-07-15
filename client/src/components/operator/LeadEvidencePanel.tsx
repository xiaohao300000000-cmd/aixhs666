import { ExternalLink, ShieldCheck } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { OperatorLead } from '@/types/operator';


export function LeadEvidencePanel({ lead }: { lead: OperatorLead }) {
  return (
    <div className="space-y-4">
      <Card className="shadow-none">
        <CardHeader className="border-b border-slate-100">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-700">Lead #{lead.id}</p>
              <CardTitle className="mt-2 text-xl">{lead.display_name}</CardTitle>
              <p className="mt-1 text-sm text-slate-500">{lead.region_text || '地区未知'} · {lead.product || lead.demand_type || '需求待确认'} · {lead.intent_stage || '阶段未知'}</p>
            </div>
            <div className="flex gap-2">
              <Badge>{lead.intent_score} 意向分</Badge>
              <Badge variant="outline">完整度 {lead.information_completeness}%</Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-5 p-5">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900"><ShieldCheck className="size-4 text-emerald-600" />AI 判断</div>
            <p className="text-sm leading-7 text-slate-600">{lead.screening?.status_reason || lead.recommended_next_step || '等待人工结合证据判断。'}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge variant="secondary">置信度 {lead.screening?.confidence ?? '—'}</Badge>
              <Badge variant="secondary">{lead.screening?.qualification_decision || lead.screening?.review_status || '未判断'}</Badge>
              {lead.screening?.policy_version && <Badge variant="outline">配置 {lead.screening.policy_version}</Badge>}
            </div>
          </div>
          <div>
            <p className="mb-2 text-sm font-semibold text-slate-900">原始证据</p>
            <div className="space-y-3">
              {lead.evidence.map((item) => (
                <div key={item.id} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-center justify-between text-xs text-slate-400"><span>{item.source_type} #{item.source_id}</span><span>+{item.score} 分</span></div>
                  <p className="mt-2 text-sm leading-7 text-slate-700">{item.text}</p>
                </div>
              ))}
            </div>
          </div>
          {!!lead.screening?.evidence.length && (
            <div>
              <p className="mb-2 text-sm font-semibold text-slate-900">模型证据链</p>
              <ul className="space-y-2 text-sm text-slate-600">
                {lead.screening.evidence.map((item) => <li key={item} className="rounded-lg bg-sky-50 px-3 py-2">{item}</li>)}
              </ul>
            </div>
          )}
          {(lead.screening?.source_url || lead.profile_url) && (
            <a className="inline-flex items-center gap-2 text-sm font-medium text-sky-700 hover:text-sky-900" href={lead.screening?.source_url || lead.profile_url || '#'} target="_blank" rel="noreferrer">
              打开原始来源 <ExternalLink className="size-4" />
            </a>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

