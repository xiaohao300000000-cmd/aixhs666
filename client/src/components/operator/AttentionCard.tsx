import { AlertTriangle, CheckCircle2, CircleDot, PlayCircle } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { AttentionItem, StatusTone } from '../../features/operator/operator-view-model';


const toneStyles: Record<StatusTone, string> = {
  neutral: 'border-slate-200 bg-white text-slate-700',
  success: 'border-emerald-200 bg-emerald-50/70 text-emerald-800',
  warning: 'border-amber-200 bg-amber-50/80 text-amber-900',
  danger: 'border-rose-200 bg-rose-50/80 text-rose-900',
  info: 'border-sky-200 bg-sky-50/80 text-sky-900',
};

const icons = {
  failed_tasks: AlertTriangle,
  review_queue: CircleDot,
  stale_workers: CheckCircle2,
  running_skills: PlayCircle,
};


export function AttentionCard({ item }: { item: AttentionItem }) {
  const Icon = icons[item.key];
  return (
    <Card className={cn('overflow-hidden shadow-none', toneStyles[item.tone])}>
      <CardContent className="flex items-start justify-between gap-4 p-4">
        <div>
          <p className="text-sm font-medium opacity-75">{item.label}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight">{item.value}</p>
          <p className="mt-1 text-xs opacity-70">{item.description}</p>
        </div>
        <span className="rounded-lg bg-white/70 p-2 shadow-sm">
          <Icon className="size-5" aria-hidden="true" />
        </span>
      </CardContent>
    </Card>
  );
}
