import {
  Activity,
  BriefcaseBusiness,
  CheckSquare2,
  HeartPulse,
  LayoutDashboard,
  Sparkles,
  UsersRound,
} from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';

import { cn } from '@/lib/utils';


const navigation = [
  { to: '/', label: '今日工作台', icon: LayoutDashboard, end: true },
  { to: '/leads', label: '线索审核', icon: UsersRound },
  { to: '/tasks', label: '任务中心', icon: CheckSquare2 },
  { to: '/customers', label: '客户中心', icon: UsersRound },
  { to: '/campaigns', label: 'Campaign 中心', icon: BriefcaseBusiness },
  { to: '/health', label: '系统健康', icon: HeartPulse },
];


export function AppShell() {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-950">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col bg-slate-950 text-white md:flex">
        <div className="border-b border-white/10 px-6 py-6">
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-xl bg-sky-500 text-white shadow-lg shadow-sky-950/30">
              <Sparkles className="size-5" />
            </span>
            <div>
              <p className="text-sm font-semibold tracking-wide">AI 获客运营台</p>
              <p className="mt-0.5 text-xs text-slate-400">Feishu · Miaoda</p>
            </div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-5">
          {navigation.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => cn(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-400 transition-colors hover:bg-white/5 hover:text-white',
                isActive && 'bg-sky-500/15 text-sky-300',
              )}
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-white/10 px-5 py-4">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Activity className="size-3.5 text-emerald-400" />
            PostgreSQL 为事实源
          </div>
        </div>
      </aside>
      <div className="md:pl-64">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur md:hidden">
          <p className="text-sm font-semibold text-slate-950">AI 获客运营台</p>
          <nav className="mt-3 flex gap-2 overflow-x-auto pb-1">
            {navigation.map(({ to, label, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => cn(
                  'shrink-0 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600',
                  isActive && 'border-slate-950 bg-slate-950 text-white',
                )}
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </header>
        <Outlet />
      </div>
    </div>
  );
}
