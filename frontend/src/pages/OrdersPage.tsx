import { CheckCircle2, ClipboardPlus, Pencil, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useOutletContext } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { customerName, formatDateTime, money, statusLabel } from "../lib/format";
import { refreshCrm } from "../lib/query";
import { useCrm } from "../features/crm/useCrm";

type Filter = "active" | "ready" | "all";
export function OrdersPage() {
  const { openEntity, openDetail } = useOutletContext<AppOutlet>(); const crm = useCrm(); const [filter, setFilter] = useState<Filter>("active");
  const action = useMutation({ mutationFn: ({ id, value }: { id: number; value: "ready" | "in_progress" }) => api.orderStatus(id, value), onSuccess: refreshCrm });
  if (crm.isPending) return <Spinner />;
  const orders = (crm.data?.orders ?? []).filter((item) => filter === "all" || (filter === "active" ? !["ready", "completed"].includes(item.status) : ["ready", "completed"].includes(item.status)));
  return <div className="grid gap-5"><header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-sm font-bold text-apex">РАБОТЫ</p><h1 className="text-3xl font-black">Заказ-наряды</h1><p className="mt-1 text-muted">Управление текущими и выполненными работами</p></div><Button onClick={() => openEntity({ kind: "order" })}><ClipboardPlus size={18} />Новый заказ</Button></header>
    <div className="flex gap-2 overflow-x-auto pb-1">{([['active','В работе'],['ready','Выполненные'],['all','Все']] as const).map(([value,label]) => <Button key={value} variant={filter === value ? "primary" : "secondary"} onClick={() => setFilter(value)}>{label}</Button>)}</div>
    <div className="grid min-w-0 gap-3">{orders.length ? orders.map((item) => <Card key={item.id} className="grid cursor-pointer min-w-0 gap-4 transition hover:border-apex/50 lg:grid-cols-[1fr_auto] lg:items-center" onClick={() => openDetail({ kind: "order", value: item })}><div className="min-w-0"><div className="flex min-w-0 flex-wrap items-center gap-2"><h2 className="break-words text-lg font-black">#{item.id} · {item.brand} {item.model}</h2><span className="rounded-full bg-success/10 px-2 py-1 text-xs font-bold text-success">{statusLabel(item.status)}</span></div><p className="mt-2 break-words text-muted">{item.description}</p><div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm"><span>{customerName(item.customer_name)}</span><span className="text-muted">{formatDateTime(item.created_at)}</span><strong className="text-apex">Прибыль: {money(item.profit)}</strong></div><p className="mt-2 text-xs font-semibold text-apex">Нажмите для полной расшифровки</p></div><div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap"><Button variant="secondary" onClick={(event) => { event.stopPropagation(); openEntity({ kind: "order", value: item }); }}><Pencil size={16} />Изменить</Button>{!["ready","completed"].includes(item.status) ? <Button onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "ready" }); }} disabled={action.isPending}><CheckCircle2 size={16} />Выполнен</Button> : <Button variant="secondary" onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "in_progress" }); }} disabled={action.isPending}><RotateCcw size={16} />Вернуть в работу</Button>}</div></Card>) : <EmptyState>В этом разделе заказов не найдено</EmptyState>}</div>
  </div>;
}
