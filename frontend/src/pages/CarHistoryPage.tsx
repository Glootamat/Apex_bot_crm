import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CarFront, ClipboardCheck, ClipboardList, PackageOpen, Wrench } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { customerName, formatDateTime, money, parseCrmDate } from "../lib/format";
import { api } from "../lib/api";
import type { DiagnosticSummary, Order } from "../lib/types";
import { useCrm } from "../features/crm/useCrm";

type Filter = "all" | "labor" | "parts" | "diagnostics";
type Event = { kind: "order"; value: Order; date: string } | { kind: "diagnostic"; value: DiagnosticSummary; date: string };

export function CarHistoryPage() {
  const { carId: rawCarId } = useParams(); const carId = Number(rawCarId);
  const navigate = useNavigate(); const { openDetail } = useOutletContext<AppOutlet>(); const crm = useCrm();
  const diagnostics = useQuery({ queryKey: ["diagnostics", carId], queryFn: () => api.diagnostics(carId), enabled: Number.isInteger(carId) && carId > 0 });
  const [filter, setFilter] = useState<Filter>("all");
  const car = crm.data?.cars.find((item) => item.id === carId);
  const owner = crm.data?.customers.find((item) => item.id === car?.customer_id);
  const events = useMemo(() => {
    const orders: Event[] = (crm.data?.orders ?? []).filter((item) => item.car_id === carId && !item.archived_at).map((value) => ({ kind: "order", value, date: value.completed_at || value.created_at }));
    const cards: Event[] = (diagnostics.data ?? []).map((value) => ({ kind: "diagnostic", value, date: value.completed_at || value.updated_at || value.created_at }));
    return [...orders, ...cards].filter((event) => filter === "all" || filter === "diagnostics" && event.kind === "diagnostic" || filter === "labor" && event.kind === "order" && event.value.labor_revenue > 0 || filter === "parts" && event.kind === "order" && event.value.parts_revenue > 0).sort((a, b) => parseCrmDate(b.date).valueOf() - parseCrmDate(a.date).valueOf());
  }, [carId, crm.data?.orders, diagnostics.data, filter]);
  if (crm.isPending || diagnostics.isPending) return <Spinner />;
  if (!car) return <EmptyState>Автомобиль не найден</EmptyState>;
  return <div className="grid min-w-0 gap-5">
    <header className="flex items-start gap-3"><Button variant="ghost" className="mt-1 size-10 shrink-0 p-0" onClick={() => { void navigate(-1); }} aria-label="Назад"><ArrowLeft size={20} /></Button><div className="min-w-0"><p className="text-sm font-bold text-apex">КАРТОЧКА АВТОМОБИЛЯ</p><h1 className="break-words text-3xl font-black">История автомобиля</h1><p className="mt-1 text-muted">Все работы, запчасти и диагностики в одной ленте</p></div></header>
    <Card className="grid gap-4 sm:grid-cols-[auto_1fr_auto]"><div className="grid size-14 place-items-center rounded-2xl bg-apex/10 text-apex"><CarFront size={30} /></div><div className="min-w-0"><h2 className="break-words text-2xl font-black">{car.brand} {car.model}</h2><p className="mt-1 break-words text-muted">{[car.plate_number, car.vin].filter(Boolean).join(" · ") || "Номер и VIN не указаны"}</p><p className="mt-2 text-sm">{customerName(owner?.full_name)}{owner?.phone ? ` · ${owner.phone}` : ""}</p></div><div className="rounded-xl bg-panel-soft p-3 text-sm sm:text-right"><p className="text-muted">Текущий пробег</p><strong className="mt-1 block text-lg">{car.mileage ? `${car.mileage.toLocaleString("ru-RU")} км` : "Не указан"}</strong></div></Card>
    <div className="flex max-w-full gap-2 overflow-x-auto pb-1">{([ ["all", "Все"], ["labor", "Работы"], ["parts", "Запчасти"], ["diagnostics", "Диагностики"] ] as const).map(([value, label]) => <Button key={value} className="shrink-0" variant={filter === value ? "primary" : "secondary"} onClick={() => setFilter(value)}>{label}</Button>)}</div>
    <section className="relative grid gap-3 before:absolute before:bottom-4 before:left-6 before:top-4 before:w-px before:bg-line">{events.length ? events.map((event) => <HistoryItem key={`${event.kind}-${event.value.id}`} event={event} onOpenOrder={(order) => openDetail({ kind: "order", value: order })} onOpenDiagnostic={(id) => { void navigate(`/diagnostics/${id}`); }} />) : <div className="relative z-10"><EmptyState>В этой категории пока нет записей</EmptyState></div>}</section>
  </div>;
}

function HistoryItem({ event, onOpenOrder, onOpenDiagnostic }: { event: Event; onOpenOrder: (order: Order) => void; onOpenDiagnostic: (id: number) => void }) {
  if (event.kind === "diagnostic") { const diagnostic = event.value; return <article className="relative z-10 grid grid-cols-[48px_1fr] gap-3"><div className="grid size-12 place-items-center rounded-full border-4 border-canvas bg-info/15 text-info"><ClipboardCheck size={20} /></div><button onClick={() => onOpenDiagnostic(diagnostic.id)} className="min-w-0 rounded-2xl border border-line bg-panel p-4 text-left transition hover:border-apex/50"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-black">Диагностика {diagnostic.status === "completed" ? "завершена" : "в работе"}</p><span className={diagnostic.status === "completed" ? "text-success text-sm font-bold" : "text-apex text-sm font-bold"}>{diagnostic.status === "completed" ? "Завершена" : "Черновик"}</span></div><p className="mt-1 text-sm text-muted">{formatDateTime(event.date)}{diagnostic.mileage ? ` · ${diagnostic.mileage.toLocaleString("ru-RU")} км` : ""}</p><div className="mt-3 flex flex-wrap gap-2 text-xs"><Badge tone="text-danger" text={`Неисправно: ${diagnostic.critical}`} /><Badge tone="text-apex" text={`Внимание: ${diagnostic.attention}`} /><Badge tone="text-muted" text={`Проверено: ${diagnostic.checked}/${diagnostic.total}`} /></div></button></article>; }
  const order = event.value; const parts = order.parts ?? []; const names = parts.slice(0, 3).map((item) => item.name).join(", ");
  return <article className="relative z-10 grid grid-cols-[48px_1fr] gap-3"><div className="grid size-12 place-items-center rounded-full border-4 border-canvas bg-apex/15 text-apex"><ClipboardList size={20} /></div><button onClick={() => onOpenOrder(order)} className="min-w-0 rounded-2xl border border-line bg-panel p-4 text-left transition hover:border-apex/50"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-black">Заказ-наряд #{order.id}</p><span className="text-sm font-bold text-success">{order.status === "completed" || order.status === "ready" ? "Завершён" : "В работе"}</span></div><p className="mt-1 text-sm text-muted">{formatDateTime(event.date)}{order.mileage_at_visit ? ` · ${order.mileage_at_visit.toLocaleString("ru-RU")} км` : ""}</p><p className="mt-3 break-words font-semibold">{order.description || "Работы не указаны"}</p>{order.labor_revenue > 0 && <div className="mt-3 flex items-center gap-2 text-sm"><Wrench size={16} className="text-apex" /><span className="text-muted">Работы</span><strong className="ml-auto">{money(order.labor_revenue)}</strong></div>}{order.parts_revenue > 0 && <div className="mt-2 flex items-center gap-2 text-sm"><PackageOpen size={16} className="text-info" /><span className="min-w-0 flex-1 truncate text-muted">{names || "Запчасти"}</span><strong>{money(order.parts_revenue)}</strong></div>}<div className="mt-3 flex justify-between border-t border-line pt-3 text-sm"><span className="text-muted">Итого по заказу</span><strong className="text-apex">{money(order.labor_revenue + order.parts_revenue)}</strong></div></button></article>;
}
function Badge({ tone, text }: { tone: string; text: string }) { return <span className={`rounded-full bg-panel-soft px-2 py-1 font-bold ${tone}`}>{text}</span>; }
