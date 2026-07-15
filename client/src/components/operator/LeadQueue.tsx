import { ChevronRight, MapPin } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { LeadQueueItem } from '../../types/operator';


type LeadQueueProps = {
  leads: LeadQueueItem[];
  selectedId: number | null;
  onSelect: (leadId: number) => void;
};


export function LeadQueue({ leads, selectedId, onSelect }: LeadQueueProps) {
  return (
    <Card className="min-w-0 shadow-none">
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b border-slate-100 px-5 py-4">
        <div>
          <CardTitle className="text-base text-slate-950">线索审核队列</CardTitle>
          <p className="mt-1 text-xs text-slate-500">按意向分数与更新时间排序</p>
        </div>
        <Badge variant="outline" className="border-slate-200 text-slate-600">{leads.length} 条预览</Badge>
      </CardHeader>
      <CardContent className="p-0">
        {leads.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <p className="text-sm font-medium text-slate-700">当前没有待审核线索</p>
            <p className="mt-1 text-xs text-slate-500">新筛选结果进入后会自动出现在这里。</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {leads.map((lead) => (
              <Button
                key={lead.id}
                type="button"
                variant="ghost"
                onClick={() => onSelect(lead.id)}
                className={cn(
                  'h-auto w-full justify-start rounded-none border-0 px-5 py-4 text-left hover:bg-slate-50',
                  selectedId === lead.id && 'bg-sky-50 hover:bg-sky-50',
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-slate-900">{lead.display_name}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                        {lead.region_text && (
                          <span className="inline-flex items-center gap-1"><MapPin className="size-3" />{lead.region_text}</span>
                        )}
                        <span>{lead.demand_type || '需求待识别'}</span>
                      </div>
                    </div>
                    <span className="rounded-md bg-slate-900 px-2 py-1 text-xs font-semibold text-white">
                      {lead.intent_score}
                    </span>
                  </div>
                  <p className="mt-3 line-clamp-2 whitespace-normal text-xs leading-5 text-slate-600">
                    {lead.evidence_text || '暂无证据摘要，建议进入线索页补充上下文。'}
                  </p>
                </div>
                <ChevronRight className="ml-2 size-4 text-slate-400" aria-hidden="true" />
              </Button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
