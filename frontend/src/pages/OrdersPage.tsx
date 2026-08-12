import { CheckCircle2, ClipboardPlus, Pencil, RotateCcw } from "lucide-react";
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
    <div className="grid min-w-0 gap-3">{orders.length ? orders.map((item) => { const expanded = expandedId === item.id; return <Card key={item.id} className="grid cursor-pointer min-w-0 gap-3 transition hover:border-apex/50 lg:grid-cols-[1fr_auto] lg:items-center" onClick={() => window.matchMedia("(max-width: 1023px)").matches ? setExpandedId(expanded ? null : item.id) : openDetail({ kind: "order", value: item })}><div className="min-w-0"><div className="flex min-w-0 flex-wrap items-center gap-2"><h2 className="break-words text-lg font-black">#{item.id} · {item.brand} {item.model}</h2><span className="rounded-full bg-success/10 px-2 py-1 text-xs font-bold text-success">{statusLabel(item.status)}</span></div><div className={`${expanded ? "block" : "hidden"} lg:block`}><p className="mt-2 break-words text-muted">{item.description}</p><div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm"><span>{customerName(item.customer_name)}</span><span className="text-muted">{formatDateTime(item.created_at)}</span><strong className="text-apex">Прибыль: {money(item.profit)}</strong></div></div><p className="mt-2 text-xs font-semibold text-apex lg:hidden">{expanded ? "Скрыть подробности" : "Нажмите для подробностей"}</p><p className="mt-2 hidden text-xs font-semibold text-apex lg:block">Открыть полную карточку</p></div><div className={`${expanded ? "flex" : "hidden"} flex-col gap-2 sm:flex-row sm:flex-wrap lg:flex`}><Button variant="secondary" onClick={(event) => { event.stopPropagation(); openEntity({ kind: "order", value: item }); }}><Pencil size={16} />Изменить</Button>{!["ready","completed"].includes(item.status) ? <Button onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "ready" }); }} disabled={action.isPending}><CheckCircle2 size={16} />Выполнен</Button> : <Button variant="secondary" onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "in_progress" }); }} disabled={action.isPending}><RotateCcw size={16} />Вернуть в работу</Button>}</div></Card>; }) : <EmptyState>В этом разделе заказов не найдено</EmptyState>}</div>
  </div>;
}
