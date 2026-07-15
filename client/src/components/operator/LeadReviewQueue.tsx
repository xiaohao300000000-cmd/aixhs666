import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { OperatorLead } from '@/types/operator';


export function LeadReviewQueue({
  items,
  selectedId,
  onSelect,
}: {
  items: OperatorLead[];
  selectedId: number | null;
  onSelect: (leadId: number) => void;
}) {
  if (!items.length) {
    return <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">当前筛选下没有线索</div>;
  }
  return (
    <div className="space-y-2">
      {items.map((lead) => (
        <button
          key={lead.id}
          type="button"
          onClick={() => onSelect(lead.id)}
          className={cn(
            'w-full rounded-xl border bg-white p-4 text-left transition hover:border-sky-300 hover:shadow-sm',
            selectedId === lead.id ? 'border-sky-500 ring-2 ring-sky-100' : 'border-slate-200',
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-semibold text-slate-950">{lead.display_name}</p>
              <p className="mt-1 text-xs text-slate-500">#{lead.id} · {lead.region_text || '地区未知'} · {lead.product || lead.demand_type || '需求待确认'}</p>
            </div>
            <Badge variant={lead.intent_score >= 70 ? 'default' : 'secondary'}>{lead.intent_score} 分</Badge>
          </div>
          <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-600">{lead.evidence[0]?.text || lead.recommended_next_step || '暂无证据摘要'}</p>
          <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
            <span>{lead.screening?.intent_strength || lead.intent_stage || '待判断'}</span>
            <span>{lead.status}</span>
          </div>
        </button>
      ))}
    </div>
  );
}

