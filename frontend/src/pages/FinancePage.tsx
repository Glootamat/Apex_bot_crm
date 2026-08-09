import {
  Banknote, BarChart3, ChevronDown, CircleAlert, ClipboardList, PackageOpen,
  TrendingUp, Wrench,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { formatDateTime, money, parseCrmDate } from "../lib/format";
import type { Order } from "../lib/types";
import { useCrm } from "../features/crm/useCrm";

type Period = 1 | 7 | 30 | 0;
type Section = "revenue" | "labor" | "parts" | "profit" | null;
type View = "overview" | "analytics";

const startOfDay = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate());

export function FinancePage() {
  const crm = useCrm();
  const { openDetail } = useOutletContext<AppOutlet>();
  const [params] = useSearchParams();
  const [period, setPeriod] = useState<Period>(params.get("period") === "today" ? 1 : 30);
  const [view, setView] = useState<View>("overview");
  const [open, setOpen] = useState<Section>("profit");
  const [ordersOpen, setOrdersOpen] = useState(true);
  const customerId = Number(params.get("customer_id")) || null;
  const allOrders = crm.data?.orders ?? [];
  const customerCarIds = useMemo(() => new Set((crm.data?.cars ?? []).filter((car) => car.customer_id === customerId).map((car) => car.id)), [crm.data?.cars, customerId]);
  const completedOrders = useMemo(() => allOrders.filter((item) => ["ready", "completed"].includes(item.status) && item.completed_at && (!customerId || customerCarIds.has(item.car_id))), [allOrders, customerCarIds, customerId]);
  const window = useMemo(() => {
    const end = new Date(); const start = startOfDay(end);
    if (period > 1) start.setDate(start.getDate() - (period - 1));
    return { start, end };
  }, [period]);
  const orders = useMemo(() => completedOrders.filter((item) => !period || (parseCrmDate(item.completed_at!) >= window.start && parseCrmDate(item.completed_at!) <= window.end)), [completedOrders, period, window]);
  const previousOrders = useMemo(() => {
    if (!period) return [];
    const previousEnd = new Date(window.start); previousEnd.setMilliseconds(-1);
    const previousStart = new Date(window.start); previousStart.setDate(previousStart.getDate() - period);
    return completedOrders.filter((item) => parseCrmDate(item.completed_at!) >= previousStart && parseCrmDate(item.completed_at!) <= previousEnd);
  }, [completedOrders, period, window]);
  if (crm.isPending) return <Spinner />;

  const totals = calculate(orders); const previous = calculate(previousOrders);
  const margin = totals.revenue ? Math.round(totals.profit / totals.revenue * 100) : 0;
  const change = previous.revenue ? Math.round((totals.revenue - previous.revenue) / previous.revenue * 100) : null;
  const sections = [
    { key: "revenue" as const, label: "Выручка", value: totals.revenue, hint: `${orders.length} заказов`, icon: Banknote, color: "text-info", rows: [["Работы", totals.labor], ["Продажа запчастей", totals.partsRevenue]] as const },
    { key: "labor" as const, label: "Доход от работ", value: totals.labor, hint: `${totals.revenue ? Math.round(totals.labor / totals.revenue * 100) : 0}% выручки`, icon: Wrench, color: "text-apex", rows: [["Оплачено за работы", totals.labor]] as const },
    { key: "parts" as const, label: "Запчасти и наценка", value: totals.markup, hint: `Закупка ${money(totals.partsCost)}`, icon: PackageOpen, color: "text-info", rows: [["Продажа", totals.partsRevenue], ["Закупка", totals.partsCost], ["Доп. прибыль", totals.extraPartsProfit], ["Наценка / прибыль", totals.markup]] as const },
    { key: "profit" as const, label: "Чистый заработок", value: totals.profit, hint: `Маржинальность ${margin}%`, icon: TrendingUp, color: "text-success", rows: [["Работы", totals.labor], ["Прибыль с запчастей", totals.markup], ["Итого", totals.profit]] as const },
  ];
  const attention = allOrders.filter((item) => !item.archived_at && !["ready", "completed"].includes(item.status));
  const scheduled = (crm.data?.appointments ?? []).filter((item) => item.status === "scheduled");
  const chart = dailyProfit(orders, period === 0 ? 30 : period, window.end);

  return <div className="grid min-w-0 gap-6">
    <header><p className="text-sm font-bold text-apex">АНАЛИТИКА</p><h1 className="text-3xl font-black">Финансы</h1><p className="mt-1 text-muted">Доходы, прибыль и состояние заказов</p></header>
    <div className="grid grid-cols-2 rounded-xl border border-line bg-panel-soft p-1 sm:max-w-md">
      <button className={`rounded-lg px-3 py-2 text-sm font-bold ${view === "overview" ? "bg-apex text-black" : "text-muted"}`} onClick={() => setView("overview")}>Обзор</button>
      <button className={`rounded-lg px-3 py-2 text-sm font-bold ${view === "analytics" ? "bg-apex text-black" : "text-muted"}`} onClick={() => setView("analytics")}><span className="inline-flex items-center gap-2"><BarChart3 size={16} />Аналитика</span></button>
    </div>
    <div className="flex max-w-full gap-2 overflow-x-auto pb-1">{([[1,"Сегодня"],[7,"7 дней"],[30,"30 дней"],[0,"Всё время"]] as const).map(([value, label]) => <Button className="shrink-0" key={value} variant={period === value ? "primary" : "secondary"} onClick={() => setPeriod(value)}>{label}</Button>)}</div>
    {view === "overview" ? <Overview sections={sections} open={open} setOpen={setOpen} orders={orders} ordersOpen={ordersOpen} setOrdersOpen={setOrdersOpen} openDetail={openDetail} totals={totals} margin={margin} /> : <Analytics totals={totals} previous={previous} change={change} margin={margin} chart={chart} attention={attention} scheduled={scheduled} openDetail={openDetail} />}
  </div>;
}

function Overview({ sections, open, setOpen, orders, ordersOpen, setOrdersOpen, openDetail, totals, margin }: { sections: { key: Exclude<Section, null>; label: string; value: number; hint: string; icon: typeof Banknote; color: string; rows: readonly (readonly [string, number])[] }[]; open: Section; setOpen: (value: Section) => void; orders: Order[]; ordersOpen: boolean; setOrdersOpen: (value: boolean) => void; openDetail: AppOutlet["openDetail"]; totals: ReturnType<typeof calculate>; margin: number }) {
  return <>
    <section className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">{sections.map(({ key, label, value, hint, icon: Icon, color, rows }) => <Card key={key} className={`cursor-pointer transition hover:border-apex/50 ${open === key ? "border-apex/60" : ""}`} onClick={() => setOpen(open === key ? null : key)}><div className="flex items-start justify-between"><Icon className={color} /><ChevronDown className={`text-muted transition ${open === key ? "rotate-180 text-apex" : ""}`} /></div><p className="mt-5 text-sm text-muted">{label}</p><strong className="mt-1 block break-words text-2xl font-black">{money(value)}</strong><p className="mt-1 text-xs text-muted">{hint}</p>{open === key && <dl className="mt-4 grid gap-2 border-t border-line pt-3">{rows.map(([name, amount]) => <div key={name} className="flex min-w-0 justify-between gap-3 text-sm"><dt className="text-muted">{name}</dt><dd className="shrink-0 font-bold">{money(amount)}</dd></div>)}</dl>}</Card>)}</section>
    <OrdersCard orders={orders} open={ordersOpen} setOpen={setOrdersOpen} openDetail={openDetail} />
    <Card className="grid gap-3 sm:grid-cols-3"><Metric label="Средний чек" value={money(orders.length ? totals.revenue / orders.length : 0)} /><Metric label="Средняя прибыль" value={money(orders.length ? totals.profit / orders.length : 0)} /><Metric label="Маржинальность" value={`${margin}%`} /></Card>
  </>;
}

function Analytics({ totals, previous, change, margin, chart, attention, scheduled, openDetail }: { totals: ReturnType<typeof calculate>; previous: ReturnType<typeof calculate>; change: number | null; margin: number; chart: { label: string; value: number }[]; attention: Order[]; scheduled: { id: number }[]; openDetail: AppOutlet["openDetail"] }) {
  const partsPercent = totals.revenue ? Math.round(totals.partsRevenue / totals.revenue * 100) : 0;
  return <div className="grid gap-4">
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Выручка" value={money(totals.revenue)} hint={change === null ? "Нет данных для сравнения" : `${change >= 0 ? "+" : ""}${change}% к прошлому периоду`} positive={(change ?? 0) >= 0} /><Metric label="Прибыль" value={money(totals.profit)} hint={`Было ${money(previous.profit)}`} positive={totals.profit >= previous.profit} /><Metric label="Средний чек" value={money(totals.count ? totals.revenue / totals.count : 0)} hint={`${totals.count} завершённых заказов`} /><Metric label="Маржинальность" value={`${margin}%`} hint={`Работы ${100 - partsPercent}% · запчасти ${partsPercent}%`} /></section>
    <ProfitChart items={chart} total={totals.profit} />
    <section className="grid gap-4 lg:grid-cols-2"><Card><h2 className="text-lg font-black">Структура выручки</h2><div className="mt-5 flex items-center gap-5"><div className="grid h-28 w-28 shrink-0 place-items-center rounded-full" style={{ background: `conic-gradient(#ffd400 0 ${100 - partsPercent}%, #38d996 ${100 - partsPercent}% 100%)` }}><div className="grid h-20 w-20 place-items-center rounded-full bg-canvas text-center text-xs font-bold">{money(totals.revenue)}</div></div><dl className="grid flex-1 gap-3 text-sm"><div className="flex justify-between"><dt className="text-muted">Работы</dt><dd className="font-bold text-apex">{money(totals.labor)}</dd></div><div className="flex justify-between"><dt className="text-muted">Запчасти</dt><dd className="font-bold text-success">{money(totals.partsRevenue)}</dd></div><div className="flex justify-between border-t border-line pt-3"><dt className="text-muted">Наценка</dt><dd className="font-bold">{money(totals.markup)}</dd></div></dl></div></Card>
      <Card><h2 className="text-lg font-black">Требует внимания</h2><p className="mt-1 text-sm text-muted">Быстрый контроль незавершённых процессов</p><div className="mt-4 grid gap-2"><AttentionRow icon={<ClipboardList size={18} />} label="Заказы в работе" value={attention.length} tone="text-danger" /><AttentionRow icon={<CircleAlert size={18} />} label="Ожидают клиента" value={scheduled.length} tone="text-apex" />{attention.slice(0, 2).map((item) => <button key={item.id} onClick={() => openDetail({ kind: "order", value: item })} className="flex items-center justify-between rounded-xl bg-panel-soft px-3 py-2 text-left text-sm hover:bg-line"><span className="truncate">#{item.id} · {item.brand} {item.model}</span><span className="text-muted">Открыть</span></button>)}</div></Card>
    </section>
  </div>;
}

function ProfitChart({ items, total }: { items: { label: string; value: number }[]; total: number }) {
  const width = 760; const height = 260; const left = 58; const right = 18; const top = 20; const bottom = 42;
  const plotWidth = width - left - right; const plotHeight = height - top - bottom;
  const rawMax = Math.max(...items.map((item) => item.value), 1);
  const step = rawMax <= 10_000 ? 2_500 : rawMax <= 50_000 ? 10_000 : rawMax <= 100_000 ? 25_000 : 50_000;
  const max = Math.max(step, Math.ceil(rawMax / step) * step);
  const points = items.map((item, index) => ({ ...item, x: left + (items.length === 1 ? plotWidth / 2 : index / (items.length - 1) * plotWidth), y: top + plotHeight - item.value / max * plotHeight }));
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = points.length ? `${left},${top + plotHeight} ${line} ${left + plotWidth},${top + plotHeight}` : "";
  const yTicks = [0, .25, .5, .75, 1];
  const labelEvery = Math.max(1, Math.ceil(items.length / 7));
  return <Card className="overflow-hidden border-apex/20 bg-gradient-to-br from-panel to-panel-soft">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-black">Динамика прибыли</h2><p className="mt-1 text-sm text-muted">Ваш заработок по завершённым заказ-нарядам</p></div><div className="text-right"><strong className="block text-xl text-success">{money(total)}</strong><span className="text-xs text-muted">прибыль за выбранный период</span></div></div>
    <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-canvas/40 p-2">
      <svg className="h-auto min-w-[620px] w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="График прибыли по дням">
        <defs><linearGradient id="revenueArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#ffd400" stopOpacity="0.42" /><stop offset="100%" stopColor="#ffd400" stopOpacity="0.02" /></linearGradient><filter id="revenueGlow"><feGaussianBlur stdDeviation="3" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter></defs>
        {yTicks.map((tick) => { const y = top + plotHeight - tick * plotHeight; return <g key={tick}><line x1={left} y1={y} x2={left + plotWidth} y2={y} stroke="#273440" strokeWidth="1" strokeDasharray={tick ? "4 6" : undefined} /><text x={left - 10} y={y + 4} textAnchor="end" fill="#8391a2" fontSize="11">{formatCompact(max * tick)}</text></g>; })}
        {area && <polygon points={area} fill="url(#revenueArea)" />}
        {points.length === 1 && points[0] ? <line x1={left} y1={points[0].y} x2={left + plotWidth} y2={points[0].y} stroke="#ffd400" strokeWidth="4" strokeLinecap="round" filter="url(#revenueGlow)" /> : <polyline points={line} fill="none" stroke="#ffd400" strokeWidth="4" strokeLinejoin="round" strokeLinecap="round" filter="url(#revenueGlow)" />}
        {points.map((point, index) => <g key={`${point.label}-${index}`} className="group"><circle cx={point.x} cy={point.y} r="10" fill="transparent"><title>{point.label}: {money(point.value)}</title></circle><circle cx={point.x} cy={point.y} r={point.value ? 4.5 : 2.5} fill={point.value ? "#ffd400" : "#586574"} stroke="#0b1118" strokeWidth="3"><title>{point.label}: {money(point.value)}</title></circle>{(index % labelEvery === 0 || index === points.length - 1) && <text x={point.x} y={height - 14} textAnchor="middle" fill="#8391a2" fontSize="11">{point.label}</text>}</g>)}
      </svg>
    </div>
    <div className="mt-3 flex items-center gap-2 text-xs text-muted"><span className="size-2.5 rounded-full bg-apex shadow-[0_0_10px_#ffd400]" />Прибыль: работы + наценка на запчасти</div>
  </Card>;
}

function formatCompact(value: number) { if (value >= 1_000_000) return `${(value / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}м`; if (value >= 1_000) return `${Math.round(value / 1_000)}к`; return String(Math.round(value)); }

function OrdersCard({ orders, open, setOpen, openDetail }: { orders: Order[]; open: boolean; setOpen: (value: boolean) => void; openDetail: AppOutlet["openDetail"] }) { return <Card><button type="button" className="flex w-full flex-wrap items-center justify-between gap-3 text-left" onClick={() => setOpen(!open)}><div><h2 className="text-lg font-black">Заказы в расчёте</h2><p className="mt-1 text-sm text-muted">Подробная расшифровка каждой суммы</p></div><span className="flex items-center gap-2"><strong className="text-apex">{orders.length}</strong><ChevronDown className={`transition ${open ? "rotate-180" : ""}`} /></span></button>{open && <div className="mt-4 grid gap-2">{orders.length ? orders.map((item) => <button key={item.id} type="button" onClick={() => openDetail({ kind: "order", value: item })} className="grid min-w-0 gap-2 rounded-xl bg-panel-soft p-3 text-left transition hover:bg-line sm:grid-cols-[1fr_auto] sm:items-center"><div className="min-w-0"><p className="break-words font-bold">#{item.id} · {item.brand} {item.model}</p><p className="mt-1 break-words text-sm text-muted">{formatDateTime(item.completed_at || item.created_at)} · {item.description}</p></div><div className="grid grid-cols-2 gap-x-4 text-sm sm:text-right"><span className="text-muted">Выручка</span><strong>{money(item.labor_revenue + item.parts_revenue)}</strong><span className="text-muted">Прибыль</span><strong className="text-success">{money(item.profit)}</strong></div></button>) : <EmptyState>За выбранный период заказов нет</EmptyState>}</div>}</Card>; }
function AttentionRow({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number; tone: string }) { return <div className="flex items-center justify-between rounded-xl bg-panel-soft p-3"><span className={`flex items-center gap-2 ${tone}`}>{icon}{label}</span><strong className={tone}>{value}</strong></div>; }
function Metric({ label, value, hint, positive }: { label: string; value: string; hint?: string; positive?: boolean }) { return <div className="rounded-xl bg-panel-soft p-4"><p className="text-sm text-muted">{label}</p><strong className="mt-1 block text-xl font-black">{value}</strong>{hint && <p className={`mt-1 text-xs ${positive === undefined ? "text-muted" : positive ? "text-success" : "text-danger"}`}>{hint}</p>}</div>; }
function calculate(orders: Order[]) { const labor = orders.reduce((sum, x) => sum + x.labor_revenue, 0); const partsRevenue = orders.reduce((sum, x) => sum + x.parts_revenue, 0); const partsCost = orders.reduce((sum, x) => sum + x.parts_cost, 0); const extraPartsProfit = orders.reduce((sum, x) => sum + x.parts_profit, 0); return { count: orders.length, labor, partsRevenue, partsCost, extraPartsProfit, markup: partsRevenue - partsCost + extraPartsProfit, revenue: labor + partsRevenue, profit: orders.reduce((sum, x) => sum + x.profit, 0) }; }
function dailyProfit(orders: Order[], days: number, end: Date) { const start = startOfDay(end); start.setDate(start.getDate() - (days - 1)); return Array.from({ length: days }, (_, index) => { const day = new Date(start); day.setDate(start.getDate() + index); const next = new Date(day); next.setDate(day.getDate() + 1); const value = orders.filter((order) => { const date = parseCrmDate(order.completed_at!); return date >= day && date < next; }).reduce((sum, order) => sum + order.profit, 0); return { label: days <= 7 ? day.toLocaleDateString("ru-RU", { weekday: "short" }).slice(0, 2) : String(day.getDate()), value }; }); }
