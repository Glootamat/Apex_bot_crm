import { CalendarPlus, CarFront, CircleDollarSign, ClipboardPlus, Search, UserPlus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useOutletContext } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { api } from "../lib/api";
import { DASHBOARD_KEY } from "../lib/query";
import { formatDateTime, money } from "../lib/format";
import { Button, Card, EmptyState, Spinner } from "../components/ui";

export function DashboardPage() {
  const navigate = useNavigate();
  const { openEntity, openDetail } = useOutletContext<AppOutlet>();
  const dashboard = useQuery({ queryKey: DASHBOARD_KEY, queryFn: api.dashboard });
  if (dashboard.isPending) return <Spinner />;
  if (!dashboard.data) return <EmptyState>Не удалось загрузить показатели</EmptyState>;
  const greeting = new Date().getHours() < 12 ? "Доброе утро" : new Date().getHours() < 18 ? "Добрый день" : "Добрый вечер";
  return <div className="grid gap-7">
    <header><p className="text-sm font-bold tracking-wide text-apex">APEX AUTO</p><h1 className="mt-1 text-3xl font-black sm:text-4xl">{greeting}, Дмитрий</h1><p className="mt-2 text-muted">Автосервис под контролем</p></header>
    <section className="grid grid-cols-2 gap-3">
      <Card className="cursor-pointer p-3 transition hover:border-apex/50" onClick={() => void navigate("/orders")}><ClipboardPlus className="text-success" size={20} /><p className="mt-3 text-xs text-muted sm:text-sm">Заказов в работе</p><strong className="mt-1 block text-2xl font-black">{dashboard.data.active_orders}</strong></Card>
      <Card className="cursor-pointer p-3 transition hover:border-apex/50" onClick={() => void navigate("/calendar")}><CalendarPlus className="text-info" size={20} /><p className="mt-3 text-xs text-muted sm:text-sm">Записей впереди</p><strong className="mt-1 block text-2xl font-black">{dashboard.data.upcoming_appointments}</strong></Card>
    </section>
    <section><h2 className="mb-3 text-lg font-black">Быстрые действия</h2><div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4"><Button onClick={() => openEntity({ kind: "order" })}><ClipboardPlus size={18} />Новый заказ</Button><Button variant="secondary" onClick={() => openEntity({ kind: "appointment" })}><CalendarPlus size={18} />Новая запись</Button><Button variant="secondary" onClick={() => openEntity({ kind: "customer" })}><UserPlus size={18} />Новый клиент</Button><Button variant="secondary" onClick={() => { void navigate("/search"); }}><Search size={18} />Найти в CRM</Button></div></section>
    <section className="grid min-w-0 gap-5 xl:grid-cols-2"><div className="min-w-0"><div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-black">Ближайшие записи</h2><Button variant="ghost" onClick={() => { void navigate("/calendar"); }}>Все записи</Button></div><div className="grid min-w-0 gap-2">{dashboard.data.appointments.length ? dashboard.data.appointments.slice(0, 4).map((item) => <Card key={item.id} className="flex cursor-pointer min-w-0 items-center gap-3 p-3 transition hover:border-apex/50" onClick={() => openDetail({ kind: "appointment", value: item })}><div className="grid size-11 shrink-0 place-items-center rounded-xl bg-info/10 text-info"><CarFront size={20} /></div><div className="min-w-0"><p className="truncate font-bold">{item.brand} {item.model}</p><p className="truncate text-sm text-muted">{item.description}</p></div><time className="ml-auto hidden shrink-0 text-right text-sm font-semibold sm:block">{formatDateTime(item.starts_at)}</time></Card>) : <EmptyState>Записей пока нет</EmptyState>}</div></div>
      <div className="min-w-0"><div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-black">Заказы в работе</h2><Button variant="ghost" onClick={() => { void navigate("/orders"); }}>Все заказы</Button></div><div className="grid min-w-0 gap-2">{dashboard.data.orders.length ? dashboard.data.orders.slice(0, 4).map((item) => <Card key={item.id} className="flex cursor-pointer min-w-0 items-center gap-3 p-3 transition hover:border-apex/50" onClick={() => openDetail({ kind: "order", value: item })}><div className="grid size-11 shrink-0 place-items-center rounded-xl bg-success/10 text-success"><ClipboardPlus size={20} /></div><div className="min-w-0"><p className="truncate font-bold">#{item.id} · {item.brand} {item.model}</p><p className="truncate text-sm text-muted">{item.description}</p></div><strong className="ml-auto hidden shrink-0 sm:block">{money(item.profit)}</strong></Card>) : <EmptyState>Активных заказов нет</EmptyState>}</div></div></section>
    <Card className="cursor-pointer transition hover:border-apex/50" onClick={() => void navigate("/finance?period=today")}><CircleDollarSign className="text-apex" /><p className="mt-4 text-sm text-muted">Заработок за сегодня</p><strong className="mt-1 block text-3xl font-black">{money(dashboard.data.today_profit)}</strong><p className="mt-2 text-xs font-semibold text-apex">Нажмите, чтобы увидеть источники прибыли</p></Card>
  </div>;
}
