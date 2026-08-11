import {
  Banknote, BarChart3, BrainCircuit, ChevronDown, CircleAlert, ClipboardList, PackageOpen,
  TrendingUp, Wrench,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useOutletContext, useSearchParams } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { formatDateTime, money, parseCrmDate } from "../lib/format";
import type { Order } from "../lib/types";
import { useCrm } from "../features/crm/useCrm";
import { api } from "../lib/api";
import type { AiUsageSummary } from "../lib/types";
import { calculateFinance } from "../lib/finance";

type Period = 1 | 7 | 30 | 0;
type Section = "revenue" | "labor" | "parts" | "profit" | null;
type View = "overview" | "analytics" | "ai";

const startOfDay = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate());

export function FinancePage() {
  const crm = useCrm();
  const account = useQuery({ queryKey: ["account"], queryFn: api.account, retry: false });
  const { openDetail } = useOutletContext<AppOutlet>();
  const [params] = useSearchParams();
  const [period, setPeriod] = useState<Period>(params.get("period") === "today" ? 1 : 30);
  const [view, setView] = useState<View>("overview");
  const [open, setOpen] = useState<Section>("profit");
  const [ordersOpen, setOrdersOpen] = useState(true);
  const customerId = Number(params.get("customer_id")) || null;
  const allOrders = useMemo(() => crm.data?.orders ?? [], [crm.data?.orders]);
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
  const aiUsage = useQuery({ queryKey: ["ai-usage", period], queryFn: () => api.aiUsage(period), enabled: view === "ai" && Boolean(account.data?.platform_admin), retry: false });
  if (crm.isPending) return <Spinner />;

  const totals = calculateFinance(orders); const previous = calculateFinance(previousOrders);
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
    <div className={`grid w-full rounded-xl border border-line bg-panel-soft p-1 ${account.data?.platform_admin ? "grid-cols-3 sm:max-w-xl" : "grid-cols-2 sm:max-w-md"}`}>
      <button aria-label="Обзор финансов" className={`min-w-0 rounded-lg px-2 py-2 text-xs font-bold sm:px-3 sm:text-sm ${view === "overview" ? "bg-apex text-black" : "text-muted"}`} onClick={() => setView("overview")}>Обзор</button>
      <button aria-label="Аналитика финансов" className={`min-w-0 rounded-lg px-2 py-2 text-xs font-bold sm:px-3 sm:text-sm ${view === "analytics" ? "bg-apex text-black" : "text-muted"}`} onClick={() => setView("analytics")}><span className="inline-flex items-center justify-center gap-1.5"><BarChart3 size={16} /><span className="hidden sm:inline">Аналитика</span><span className="sm:hidden">Графики</span></span></button>
      {Boolean(account.data?.platform_admin) && <button aria-label="Расходы на ИИ" className={`min-w-0 rounded-lg px-2 py-2 text-xs font-bold sm:px-3 sm:text-sm ${view === "ai" ? "bg-apex text-black" : "text-muted"}`} onClick={() => setView("ai")}><span className="inline-flex items-center justify-center gap-1.5"><BrainCircuit size={16} /><span className="hidden sm:inline">ИИ-расходы</span><span className="sm:hidden">ИИ</span></span></button>}
    </div>
    <div className="flex max-w-full gap-2 overflow-x-auto pb-1">{([[1,"Сегодня"],[7,"7 дней"],[30,"30 дней"],[0,"Всё время"]] as const).map(([value, label]) => <Button className="shrink-0" key={value} variant={period === value ? "primary" : "secondary"} onClick={() => setPeriod(value)}>{label}</Button>)}</div>
    {view === "overview" ? <Overview sections={sections} open={open} setOpen={setOpen} orders={orders} ordersOpen={ordersOpen} setOrdersOpen={setOrdersOpen} openDetail={openDetail} totals={totals} margin={margin} /> : view === "analytics" ? <Analytics totals={totals} previous={previous} change={change} margin={margin} chart={chart} attention={attention} scheduled={scheduled} openDetail={openDetail} /> : <AiExpenses data={aiUsage.data} pending={aiUsage.isPending} />}
  </div>;
}

function AiExpenses({ data, pending }: { data?: AiUsageSummary; pending: boolean }) {
  if (pending) return <Spinner label="Загружаю расходы на ИИ…" />;
  if (!data) return <EmptyState>Данные об использовании ИИ пока недоступны.</EmptyState>;
  const labels: Record<string, string> = { vision: "Распознавание чека", vehicle_recognition: "Распознавание автомобиля", vin_decode: "VIN-декодирование" };
  const rub = (value: number) => `${Math.round(value * data.usd_to_rub_rate).toLocaleString("ru-RU")} ₽`;
  return <div className="grid gap-4">
    <Card className="border-apex/30 bg-gradient-to-br from-panel to-panel-soft"><div className="flex items-start gap-3"><BrainCircuit className="mt-1 text-apex" size={25} /><div><h2 className="text-xl font-black">Расходы на ИИ</h2><p className="mt-1 text-sm text-muted">Расчёт: $1 = {data.usd_to_rub_rate.toLocaleString("ru-RU")} ₽. Курс можно изменить в настройках сервера.</p></div></div><section className="mt-5 grid gap-3 sm:grid-cols-4"><Metric label="Расходы" value={rub(data.cost_usd)} /><Metric label="Запросов" value={String(data.requests)} /><Metric label="Средняя стоимость" value={rub(data.requests ? data.cost_usd / data.requests : 0)} /><Metric label="Токенов" value={(data.input_tokens + data.output_tokens).toLocaleString("ru-RU")} hint={`Вход: ${data.input_tokens.toLocaleString("ru-RU")} · выход: ${data.output_tokens.toLocaleString("ru-RU")}`} /></section></Card>
    <AiExpenseChart items={data.daily} rate={data.usd_to_rub_rate} />
    <Card><h2 className="text-lg font-black">Разбивка по функциям</h2><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[620px] text-left text-sm"><thead className="border-b border-line text-muted"><tr><th className="pb-3 font-medium">Функция</th><th className="pb-3 font-medium">Модель</th><th className="pb-3 text-right font-medium">Запросы</th><th className="pb-3 text-right font-medium">Токены</th><th className="pb-3 text-right font-medium">Расходы</th></tr></thead><tbody>{data.by_task.length ? data.by_task.map((row) => <tr key={`${row.task_type}-${row.model}`} className="border-b border-line/70 last:border-0"><td className="py-3 font-bold">{labels[row.task_type] ?? row.task_type}</td><td className="py-3 text-muted">{row.model}</td><td className="py-3 text-right">{row.requests}</td><td className="py-3 text-right">{(row.input_tokens + row.output_tokens).toLocaleString("ru-RU")}</td><td className="py-3 text-right font-bold text-apex">{rub(row.cost_usd)}</td></tr>) : <tr><td colSpan={5} className="py-8 text-center text-muted">ИИ-запросов за выбранный период ещё не было.</td></tr>}</tbody></table></div></Card>
  </div>;
}

function AiExpenseChart({ items, rate }: { items: AiUsageSummary["daily"]; rate: number }) {
  const values = items.map((item) => ({ label: item.date.slice(5).split("-").reverse().join("."), value: item.cost_usd * rate }));
  const total = values.reduce((sum, item) => sum + item.value, 0);
  const peak = Math.max(...values.map((item) => item.value), 0);
  return <Card className="border-apex/20 bg-gradient-to-br from-panel to-panel-soft"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-black">Расходы на ИИ по дням</h2><p className="mt-1 text-sm text-muted">Компактная динамика за выбранный период</p></div><strong className="rounded-lg bg-apex/10 px-3 py-2 text-sm text-apex">{Math.round(total).toLocaleString("ru-RU")} ₽</strong></div><CompactBarChart items={values} ariaLabel="Расходы на ИИ по дням" tone="apex" formatValue={(value) => `${Math.round(value).toLocaleString("ru-RU")} ₽`} /><div className="mt-3 grid grid-cols-2 gap-2 text-sm"><div className="rounded-xl bg-canvas/60 p-3"><span className="block text-xs text-muted">Пик за день</span><strong>{Math.round(peak).toLocaleString("ru-RU")} ₽</strong></div><div className="rounded-xl bg-canvas/60 p-3"><span className="block text-xs text-muted">В среднем за день</span><strong>{Math.round(total / Math.max(values.length, 1)).toLocaleString("ru-RU")} ₽</strong></div></div></Card>;
}

function Overview({ sections, open, setOpen, orders, ordersOpen, setOrdersOpen, openDetail, totals, margin }: { sections: { key: Exclude<Section, null>; label: string; value: number; hint: string; icon: typeof Banknote; color: string; rows: readonly (readonly [string, number])[] }[]; open: Section; setOpen: (value: Section) => void; orders: Order[]; ordersOpen: boolean; setOrdersOpen: (value: boolean) => void; openDetail: AppOutlet["openDetail"]; totals: ReturnType<typeof calculateFinance>; margin: number }) {
  return <>
    <section className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">{sections.map(({ key, label, value, hint, icon: Icon, color, rows }) => <Card key={key} className={`cursor-pointer transition hover:border-apex/50 ${open === key ? "border-apex/60" : ""}`} onClick={() => setOpen(open === key ? null : key)}><div className="flex items-start justify-between"><Icon className={color} /><ChevronDown className={`text-muted transition ${open === key ? "rotate-180 text-apex" : ""}`} /></div><p className="mt-5 text-sm text-muted">{label}</p><strong className="mt-1 block break-words text-2xl font-black">{money(value)}</strong><p className="mt-1 text-xs text-muted">{hint}</p>{open === key && <dl className="mt-4 grid gap-2 border-t border-line pt-3">{rows.map(([name, amount]) => <div key={name} className="flex min-w-0 justify-between gap-3 text-sm"><dt className="text-muted">{name}</dt><dd className="shrink-0 font-bold">{money(amount)}</dd></div>)}</dl>}</Card>)}</section>
    <OrdersCard orders={orders} open={ordersOpen} setOpen={setOrdersOpen} openDetail={openDetail} />
    <Card className="grid gap-3 sm:grid-cols-3"><Metric label="Средний чек" value={money(orders.length ? totals.revenue / orders.length : 0)} /><Metric label="Средняя прибыль" value={money(orders.length ? totals.profit / orders.length : 0)} /><Metric label="Маржинальность" value={`${margin}%`} /></Card>
  </>;
}

function Analytics({ totals, previous, change, margin, chart, attention, scheduled, openDetail }: { totals: ReturnType<typeof calculateFinance>; previous: ReturnType<typeof calculateFinance>; change: number | null; margin: number; chart: { label: string; value: number }[]; attention: Order[]; scheduled: { id: number }[]; openDetail: AppOutlet["openDetail"] }) {
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
  const positiveDays = items.filter((item) => item.value > 0).length;
  const bestDay = Math.max(...items.map((item) => item.value), 0);
  return <Card className="border-success/25 bg-gradient-to-br from-panel to-panel-soft"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-black">Прибыль по дням</h2><p className="mt-1 text-sm text-muted">Столбец показывает результат одного дня</p></div><div className="text-right"><strong className="block text-xl text-success">{money(total)}</strong><span className="text-xs text-muted">за период</span></div></div><CompactBarChart items={items} ariaLabel="Прибыль по дням" tone="profit" formatValue={money} /><div className="mt-3 grid grid-cols-2 gap-2 text-sm"><div className="rounded-xl bg-canvas/60 p-3"><span className="block text-xs text-muted">Прибыльных дней</span><strong>{positiveDays} из {items.length}</strong></div><div className="rounded-xl bg-canvas/60 p-3"><span className="block text-xs text-muted">Лучший день</span><strong className="text-success">{money(bestDay)}</strong></div></div></Card>;
}

function CompactBarChart({ items, ariaLabel, tone, formatValue }: { items: { label: string; value: number }[]; ariaLabel: string; tone: "apex" | "profit"; formatValue: (value: number) => string }) {
  const width = 360; const height = 154; const top = 12; const bottom = 28; const left = 8; const right = 8; const plotHeight = height - top - bottom; const plotWidth = width - left - right;
  const min = Math.min(0, ...items.map((item) => item.value)); const max = Math.max(0, ...items.map((item) => item.value)); const range = Math.max(max - min, 1); const baseline = top + max / range * plotHeight;
  const barWidth = Math.max(3, Math.min(20, plotWidth / Math.max(items.length, 1) * .62)); const step = plotWidth / Math.max(items.length, 1); const labelEvery = Math.max(1, Math.ceil(items.length / 5));
  const colors = tone === "profit" ? { positive: "#32d583", negative: "#ff5c5c" } : { positive: "#ffd600", negative: "#ff5c5c" };
  return <div className="mt-4 rounded-xl border border-line bg-canvas/60 p-2"><svg className="h-auto w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}><line x1={left} y1={baseline} x2={width - right} y2={baseline} stroke="#52606d" strokeWidth="1" />{[.25, .5, .75].map((tick) => <line key={tick} x1={left} y1={top + plotHeight * tick} x2={width - right} y2={top + plotHeight * tick} stroke="#273440" strokeWidth="1" strokeDasharray="3 5" />)}{items.map((item, index) => { const x = left + step * index + (step - barWidth) / 2; const y = top + (max - Math.max(item.value, 0)) / range * plotHeight; const bottomY = top + (max - Math.min(item.value, 0)) / range * plotHeight; const isVisibleLabel = index === 0 || index === items.length - 1 || index % labelEvery === 0; return <g key={`${item.label}-${index}`}><rect x={x} y={Math.min(y, bottomY)} width={barWidth} height={Math.max(2, Math.abs(bottomY - y))} rx="2" fill={item.value < 0 ? colors.negative : colors.positive}><title>{item.label}: {formatValue(item.value)}</title></rect>{isVisibleLabel && <text x={x + barWidth / 2} y={height - 8} textAnchor="middle" fill="#96a1ad" fontSize="10">{item.label}</text>}</g>; })}</svg></div>;
}

function OrdersCard({ orders, open, setOpen, openDetail }: { orders: Order[]; open: boolean; setOpen: (value: boolean) => void; openDetail: AppOutlet["openDetail"] }) { return <Card><button type="button" className="flex w-full flex-wrap items-center justify-between gap-3 text-left" onClick={() => setOpen(!open)}><div><h2 className="text-lg font-black">Заказы в расчёте</h2><p className="mt-1 text-sm text-muted">Подробная расшифровка каждой суммы</p></div><span className="flex items-center gap-2"><strong className="text-apex">{orders.length}</strong><ChevronDown className={`transition ${open ? "rotate-180" : ""}`} /></span></button>{open && <div className="mt-4 grid gap-2">{orders.length ? orders.map((item) => <button key={item.id} type="button" onClick={() => openDetail({ kind: "order", value: item })} className="grid min-w-0 gap-2 rounded-xl bg-panel-soft p-3 text-left transition hover:bg-line sm:grid-cols-[1fr_auto] sm:items-center"><div className="min-w-0"><p className="break-words font-bold">#{item.id} · {item.brand} {item.model}</p><p className="mt-1 break-words text-sm text-muted">{formatDateTime(item.completed_at || item.created_at)} · {item.description}</p></div><div className="grid grid-cols-2 gap-x-4 text-sm sm:text-right"><span className="text-muted">Выручка</span><strong>{money(item.labor_revenue + item.parts_revenue)}</strong><span className="text-muted">Прибыль</span><strong className="text-success">{money(item.profit)}</strong></div></button>) : <EmptyState>За выбранный период заказов нет</EmptyState>}</div>}</Card>; }
function AttentionRow({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number; tone: string }) { return <div className="flex items-center justify-between rounded-xl bg-panel-soft p-3"><span className={`flex items-center gap-2 ${tone}`}>{icon}{label}</span><strong className={tone}>{value}</strong></div>; }
function Metric({ label, value, hint, positive }: { label: string; value: string; hint?: string; positive?: boolean }) { return <div className="rounded-xl bg-panel-soft p-4"><p className="text-sm text-muted">{label}</p><strong className="mt-1 block text-xl font-black">{value}</strong>{hint && <p className={`mt-1 text-xs ${positive === undefined ? "text-muted" : positive ? "text-success" : "text-danger"}`}>{hint}</p>}</div>; }
function dailyProfit(orders: Order[], days: number, end: Date) { const start = startOfDay(end); start.setDate(start.getDate() - (days - 1)); return Array.from({ length: days }, (_, index) => { const day = new Date(start); day.setDate(start.getDate() + index); const next = new Date(day); next.setDate(day.getDate() + 1); const value = orders.filter((order) => { const date = parseCrmDate(order.completed_at!); return date >= day && date < next; }).reduce((sum, order) => sum + order.profit, 0); return { label: days <= 7 ? day.toLocaleDateString("ru-RU", { weekday: "short" }).slice(0, 2) : String(day.getDate()), value }; }); }
