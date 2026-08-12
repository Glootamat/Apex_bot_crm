import { CalendarPlus, CarFront, ClipboardCheck, Plus, UserPlus, Wrench } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useOutletContext } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { api } from "../lib/api";
import { DASHBOARD_KEY } from "../lib/query";
import { formatDateTime, money, statusLabel } from "../lib/format";
import { Card, EmptyState, Spinner } from "../components/ui";

export function DashboardPage() {
  const navigate = useNavigate(); const { openEntity, openDetail } = useOutletContext<AppOutlet>();
  const dashboard = useQuery({ queryKey: DASHBOARD_KEY, queryFn: api.dashboard });
  const account = useQuery({ queryKey: ["account"], queryFn: api.account, retry: false });
  if (dashboard.isPending) return <Spinner />;
  if (!dashboard.data) return <EmptyState>Не удалось загрузить показатели</EmptyState>;
  const hour = new Date().getHours(); const greeting = hour < 12 ? "Доброе утро" : hour < 18 ? "Добрый день" : "Добрый вечер";
  const todayLabel = new Intl.DateTimeFormat("ru-RU", { weekday: "long", day: "numeric", month: "long" }).format(new Date());
  const workspaceName = account.data?.organization_name?.trim() || "Apex Auto";
  const name = account.data?.full_name?.trim() || "";
  return <div className="grid gap-5 sm:gap-6">
    <header className="pt-1"><p className="text-lg font-black tracking-tight"><span className="text-apex">{workspaceName.split(" ")[0]}</span>{workspaceName.includes(" ") && <span> {workspaceName.split(" ").slice(1).join(" ")}</span>}</p><h1 className="mt-4 text-2xl font-black sm:text-3xl">{greeting}{name ? `, ${name}!` : "!"}</h1><p className="mt-1 capitalize text-sm text-muted">{todayLabel}</p></header>

    <section className="grid grid-cols-2 gap-3"><MetricCard label="Заработок за сегодня" value={money(dashboard.data.today_profit)} change="Финансовый результат" tone="apex" onClick={() => void navigate("/finance?period=today")} /><MetricCard label="Записей впереди" value={String(dashboard.data.upcoming_appointments)} change="Ближайшие визиты" tone="success" onClick={() => void navigate("/calendar")} /></section>

    <section><h2 className="mb-3 text-sm font-black">Быстрые действия</h2><div className="grid grid-cols-4 gap-2 sm:max-w-xl"><Action icon={<Plus size={21} />} label="Новый заказ" tone="apex" onClick={() => openEntity({ kind: "order" })} /><Action icon={<CalendarPlus size={20} />} label="Новая запись" tone="info" onClick={() => openEntity({ kind: "appointment" })} /><Action icon={<UserPlus size={20} />} label="Новый клиент" tone="purple" onClick={() => openEntity({ kind: "customer" })} /><Action icon={<ClipboardCheck size={20} />} label="Диагностика" tone="success" onClick={() => void navigate("/diagnostics")} /></div></section>

    <DashboardList title="Ближайшие записи" allLabel="Все" onAll={() => void navigate("/calendar")}>{dashboard.data.appointments.length ? dashboard.data.appointments.slice(0, 4).map((item) => <button key={item.id} type="button" className="grid w-full grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-3 border-b border-line/70 py-3 text-left last:border-0" onClick={() => openDetail({ kind: "appointment", value: item })}><span className="grid size-10 place-items-center rounded-xl bg-info/10 text-info"><CarFront size={19} /></span><span className="min-w-0"><strong className="block truncate text-sm">{item.brand} {item.model}</strong><small className="block truncate text-xs text-muted">{item.description}</small></span><span className="text-right"><time className="block text-xs font-bold">{formatDateTime(item.starts_at)}</time><small className="mt-1 inline-block rounded-md bg-panel-soft px-1.5 py-0.5 text-[10px] text-muted">{statusLabel(item.status)}</small></span></button>) : <EmptyState>Записей пока нет</EmptyState>}</DashboardList>

    <DashboardList title="Заказы в работе" allLabel="Все" onAll={() => void navigate("/orders")}>{dashboard.data.orders.length ? dashboard.data.orders.slice(0, 4).map((item) => <button key={item.id} type="button" className="grid w-full grid-cols-[42px_minmax(0,1fr)_auto] items-center gap-3 border-b border-line/70 py-3 text-left last:border-0" onClick={() => openDetail({ kind: "order", value: item })}><span className="grid size-10 place-items-center rounded-xl bg-success/10 text-success"><Wrench size={19} /></span><span className="min-w-0"><strong className="block truncate text-sm">{item.brand} {item.model}</strong><small className="block truncate text-xs text-muted">{item.description}</small></span><span className="text-right"><small className="inline-block rounded-md bg-success/10 px-1.5 py-0.5 text-[10px] font-bold text-success">{statusLabel(item.status)}</small><strong className="mt-1 block text-xs">{money(item.profit)}</strong></span></button>) : <EmptyState>Активных заказов нет</EmptyState>}</DashboardList>
  </div>;
}

function MetricCard({ label, value, change, tone, onClick }: { label: string; value: string; change: string; tone: "apex" | "success"; onClick: () => void }) { const color = tone === "apex" ? "text-apex" : "text-success"; return <Card className="cursor-pointer overflow-hidden p-3 transition hover:border-apex/50" onClick={onClick}><p className="text-[11px] leading-tight text-muted">{label}</p><strong className="mt-1 block text-lg font-black sm:text-2xl">{value}</strong><p className={`mt-2 text-[10px] font-bold ${color}`}>{change}</p><div className={`mt-2 h-1.5 w-2/3 rounded-full ${tone === "apex" ? "bg-apex/80" : "bg-success/80"}`} /></Card>; }
function Action({ icon, label, tone, onClick }: { icon: React.ReactNode; label: string; tone: "apex" | "info" | "purple" | "success"; onClick: () => void }) { const tones = { apex: "bg-apex text-black", info: "bg-info/20 text-info", purple: "bg-purple-400/20 text-purple-300", success: "bg-success/20 text-success" }; return <button type="button" className="grid min-w-0 justify-items-center gap-1.5 text-center" onClick={onClick}><span className={`grid size-11 place-items-center rounded-2xl transition hover:scale-105 ${tones[tone]}`}>{icon}</span><span className="text-[10px] font-semibold leading-tight text-muted">{label}</span></button>; }
function DashboardList({ title, allLabel, onAll, children }: React.PropsWithChildren<{ title: string; allLabel: string; onAll: () => void }>) { return <Card className="p-3 sm:p-4"><div className="flex items-center justify-between gap-3"><h2 className="text-sm font-black">{title}</h2><button type="button" onClick={onAll} className="text-xs font-bold text-muted hover:text-apex">{allLabel}</button></div><div className="mt-2">{children}</div></Card>; }
