import type { LucideIcon } from 'lucide-react';
import { ArrowLeft, Layers3 } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';


export default function ComingSoonPage({ title, description, icon: Icon = Layers3 }: { title: string; description: string; icon?: LucideIcon }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl items-center px-4 py-12 sm:px-6">
      <Card className="w-full shadow-none">
        <CardContent className="p-8 sm:p-12">
          <span className="flex size-12 items-center justify-center rounded-xl bg-sky-100 text-sky-700"><Icon className="size-6" /></span>
          <p className="mt-6 text-xs font-semibold uppercase tracking-[0.16em] text-sky-700">Planned Module</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">{title}</h1>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600">{description}</p>
          <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
            当前阶段只开放“今日工作台”。这里保留真实产品入口与信息架构，但不会提供未完成的写操作。
          </div>
          <Button asChild className="mt-6"><Link to="/"><ArrowLeft />返回今日工作台</Link></Button>
        </CardContent>
      </Card>
    </main>
  );
}
