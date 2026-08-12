import { CalendarDays, CarFront, CheckCircle2, ClipboardPlus, Coins, Pencil, RotateCcw, UserRound, Wrench } from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useOutletContext, useSearchParams } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { customerName, formatDateTime, money, statusLabel } from "../lib/format";
import { refreshCrm } from "../lib/query";
import { useCrm } from "../features/crm/useCrm";

type Filter = "active" | "ready" | "all";
export function OrdersPage() {
  const { openEntity, openDetail } = useOutletContext<AppOutlet>(); const crm = useCrm(); const [filter, setFilter] = useState<Filter>("active"); const [expandedId, setExpandedId] = useState<number | null>(null);
  const [params, setParams] = useSearchParams();
  const action = useMutation({ mutationFn: ({ id, value }: { id: number; value: "ready" | "in_progress" }) => api.orderStatus(id, value), onSuccess: refreshCrm });
  if (crm.isPending) return <Spinner />;
  const carId = Number(params.get("car_id")) || null; const customerId = Number(params.get("customer_id")) || null;
  const customerCars = new Set((crm.data?.cars ?? []).filter((car) => car.customer_id === customerId).map((car) => car.id));
  const orders = (crm.data?.orders ?? []).filter((item) => (!carId || item.car_id === carId) && (!customerId || customerCars.has(item.car_id)) && (filter === "all" || (filter === "active" ? !["ready", "completed"].includes(item.status) : ["ready", "completed"].includes(item.status))));
  return <div className="grid gap-5"><header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-sm font-bold text-apex">РАБОТЫ</p><h1 className="text-3xl font-black">Заказ-наряды</h1><p className="mt-1 text-muted">Управление текущими и выполненными работами</p></div><Button onClick={() => openEntity({ kind: "order" })}><ClipboardPlus size={18} />Новый заказ</Button></header>
    {(carId || customerId) && <div className="flex items-center justify-between rounded-xl bg-apex/10 p-3 text-sm"><span>Показаны связанные заказ-наряды</span><Button variant="ghost" onClick={() => setParams({})}>Сбросить</Button></div>}
    <div className="flex gap-2 overflow-x-auto pb-1">{([['active','В работе'],['ready','Выполненные'],['all','Все']] as const).map(([value,label]) => <Button key={value} variant={filter === value ? "primary" : "secondary"} onClick={() => setFilter(value)}>{label}</Button>)}</div>
    <div className="grid min-w-0 gap-3 md:grid-cols-2">{orders.length ? orders.map((item) => { const expanded = expandedId === item.id; return <Card key={item.id} className="group cursor-pointer overflow-hidden p-0 transition hover:-translate-y-0.5 hover:border-apex/50" onClick={() => window.matchMedia("(max-width: 1023px)").matches ? setExpandedId(expanded ? null : item.id) : openDetail({ kind: "order", value: item })}>
      <div className="border-b border-line bg-gradient-to-br from-panel-soft to-panel p-4">
        <div className="flex items-start gap-3"><span className="grid size-11 shrink-0 place-items-center rounded-xl bg-apex/10 text-apex"><CarFront size={22} /></span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-bold text-muted">ЗАКАЗ-НАРЯД #{item.id}</span><span className="rounded-full bg-success/10 px-2 py-1 text-[11px] font-bold text-success">{statusLabel(item.status)}</span></div><h2 className="mt-1 break-words text-xl font-black">{item.brand} {item.model}</h2>{item.plate_number && <p className="text-sm font-semibold text-muted">{item.plate_number}</p>}</div></div>
      </div>
      <div className="grid grid-cols-3 gap-px bg-line"><div className="bg-panel p-3"><CalendarDays size={15} className="mb-1 text-info"/><span className="block text-[10px] uppercase text-muted">Создан</span><strong className="mt-1 block text-xs">{formatDateTime(item.created_at)}</strong></div><div className="bg-panel p-3"><Wrench size={15} className="mb-1 text-info"/><span className="block text-[10px] uppercase text-muted">Работы</span><strong className="mt-1 block text-sm">{money(item.labor_revenue)}</strong></div><div className="bg-panel p-3"><Coins size={15} className="mb-1 text-success"/><span className="block text-[10px] uppercase text-muted">Прибыль</span><strong className="mt-1 block text-sm text-success">{money(item.profit)}</strong></div></div>
      <div className="p-4"><div className="flex items-center gap-2 text-sm"><UserRound size={16} className="shrink-0 text-muted"/><strong className="break-words">{customerName(item.customer_name)}</strong></div><p className="mt-3 line-clamp-2 break-words text-sm text-muted">{item.description || "Работы не указаны"}</p><p className="mt-3 text-xs font-semibold text-apex lg:hidden">{expanded ? "Скрыть действия" : "Нажмите для действий"}</p><p className="mt-3 hidden text-xs font-semibold text-apex lg:block">Открыть подробную карточку →</p></div>
      <div className={`${expanded ? "grid" : "hidden"} grid-cols-1 gap-2 border-t border-line p-3 sm:grid-cols-2 lg:hidden`}><Button variant="secondary" onClick={(event) => { event.stopPropagation(); openEntity({ kind: "order", value: item }); }}><Pencil size={16} />Изменить</Button>{!["ready","completed"].includes(item.status) ? <Button onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "ready" }); }} disabled={action.isPending}><CheckCircle2 size={16} />Выполнен</Button> : <Button variant="secondary" onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "in_progress" }); }} disabled={action.isPending}><RotateCcw size={16} />Вернуть в работу</Button>}</div>
    </Card>; }) : <div className="md:col-span-2"><EmptyState>В этом разделе заказов не найдено</EmptyState></div>}</div>
  </div>;
}
