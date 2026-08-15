import {
  Banknote, BarChart3, BrainCircuit, ChevronDown, PackageOpen,
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
  const chart = dailyFinance(orders, period === 0 ? 30 : period, window.end);
  return <div className="grid min-w-0 gap-6">
    <header><p className="text-sm font-bold text-apex">АНАЛИТИКА</p><h1 className="text-3xl font-black">Финансы</h1><p className="mt-1 text-muted">Доходы, прибыль и состояние заказов</p></header>
    <div className={`grid w-full rounded-xl border border-line bg-panel-soft p-1 ${account.data?.platform_admin ? "grid-cols-3 sm:max-w-xl" : "grid-cols-2 sm:max-w-md"}`}>
      <button aria-label="Обзор финансов" className={`min-w-0 rounded-lg px-2 py-2 text-xs font-bold sm:px-3 sm:text-sm ${view === "overview" ? "bg-apex text-black" : "text-muted"}`} onClick={() => setView("overview")}>Обзор</button>
      <button aria-label="Аналитика финансов" className={`min-w-0 rounded-lg px-2 py-2 text-xs font-bold sm:px-3 sm:text-sm ${view === "analytics" ? "bg-apex text-black" : "text-muted"}`} onClick={() => setView("analytics")}><span className="inline-flex items-center justify-center gap-1.5"><BarChart3 size={16} /><span className="hidden sm:inline">Аналитика</span><span className="sm:hidden">Графики</span></span></button>
      {Boolean(account.data?.platform_admin) && <button aria-label="Расходы на ИИ" className={`min-w-0 rounded-lg px-2 py-2 text-xs font-bold sm:px-3 sm:text-sm ${view === "ai" ? "bg-apex text-black" : "text-muted"}`} onClick={() => setView("ai")}><span className="inline-flex items-center justify-center gap-1.5"><BrainCircuit size={16} /><span className="hidden sm:inline">ИИ-расходы</span><span className="sm:hidden">ИИ</span></span></button>}
    </div>
    <div className="flex max-w-full gap-2 overflow-x-auto pb-1">{([[1,"Сегодня"],[7,"7 дней"],[30,"30 дней"],[0,"Всё время"]] as const).map(([value, label]) => <Button className="shrink-0" key={value} variant={period === value ? "primary" : "secondary"} onClick={() => setPeriod(value)}>{label}</Button>)}</div>
    {view === "overview" ? <Overview sections={sections} open={open} setOpen={setOpen} orders={orders} ordersOpen={ordersOpen} setOrdersOpen={setOrdersOpen} openDetail={openDetail} totals={totals} margin={margin} /> : view === "analytics" ? <Analytics totals={totals} previous={previous} change={change} margin={margin} chart={chart} orders={orders} /> : <AiExpenses data={aiUsage.data} pending={aiUsage.isPending} />}
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
  const width = 760; const height = 248; const left = 48; const right = 12; const top = 14; const bottom = 30;
  const plotWidth = width - left - right; const plotHeight = height - top - bottom;
  const max = Math.max(1, ...values.map((item) => item.value));
  const y = (value: number) => top + (max - value) / max * plotHeight;
  const line = values.map((item, index) => `${left + (values.length <= 1 ? plotWidth / 2 : index / (values.length - 1) * plotWidth)},${y(item.value)}`).join(" ");
  const labelEvery = Math.max(1, Math.ceil(values.length / 7));
  return <Card className="overflow-hidden border-info/20 bg-gradient-to-br from-panel to-[#111a26]"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-black">Динамика расходов на ИИ</h2><p className="mt-1 text-sm text-muted">Стоимость использования по дням</p></div><div className="text-right"><strong className="block text-xl">{Math.round(total).toLocaleString("ru-RU")} ₽</strong><span className="text-xs text-muted">всего за период</span></div></div><div className="mt-3 rounded-xl border border-line/70 bg-canvas/45 p-2"><svg className="h-auto w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="График расходов на искусственный интеллект">{[0, .25, .5, .75, 1].map((tick) => { const value = max * tick; const lineY = y(value); return <g key={tick}><line x1={left} y1={lineY} x2={width - right} y2={lineY} stroke="#253241" strokeWidth="1" /><text x={left - 8} y={lineY + 4} textAnchor="end" fill="#768596" fontSize="10">{formatCompact(value)}</text></g>; })}{values.length > 0 && <polygon points={`${left},${y(0)} ${line} ${width - right},${y(0)}`} fill="#ffd60018" />}{values.length > 0 && <polyline points={line} fill="none" stroke="#ffd600" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />}{values.map((item, index) => (index % labelEvery === 0 || index === values.length - 1) && <text key={`${item.label}-${index}`} x={left + (values.length <= 1 ? plotWidth / 2 : index / (values.length - 1) * plotWidth)} y={height - 8} textAnchor="middle" fill="#8391a2" fontSize="10">{item.label}</text>)}</svg></div><div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted"><span className="flex items-center gap-2"><i className="h-0.5 w-5 bg-apex" />Расходы</span><span>Пик: <b className="text-white">{Math.round(peak).toLocaleString("ru-RU")} ₽</b></span><span>В среднем: <b className="text-white">{Math.round(total / Math.max(values.length, 1)).toLocaleString("ru-RU")} ₽/день</b></span></div></Card>;
}

function Overview({ sections, open, setOpen, orders, ordersOpen, setOrdersOpen, openDetail, totals, margin }: { sections: { key: Exclude<Section, null>; label: string; value: number; hint: string; icon: typeof Banknote; color: string; rows: readonly (readonly [string, number])[] }[]; open: Section; setOpen: (value: Section) => void; orders: Order[]; ordersOpen: boolean; setOrdersOpen: (value: boolean) => void; openDetail: AppOutlet["openDetail"]; totals: ReturnType<typeof calculateFinance>; margin: number }) {
  return <>
    <section className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">{sections.map(({ key, label, value, hint, icon: Icon, color, rows }) => <Card key={key} className={`cursor-pointer transition hover:border-apex/50 ${open === key ? "border-apex/60" : ""}`} onClick={() => setOpen(open === key ? null : key)}><div className="flex items-start justify-between"><Icon className={color} /><ChevronDown className={`text-muted transition ${open === key ? "rotate-180 text-apex" : ""}`} /></div><p className="mt-5 text-sm text-muted">{label}</p><strong className="mt-1 block break-words text-2xl font-black">{money(value)}</strong><p className="mt-1 text-xs text-muted">{hint}</p>{open === key && <dl className="mt-4 grid gap-2 border-t border-line pt-3">{rows.map(([name, amount]) => <div key={name} className="flex min-w-0 justify-between gap-3 text-sm"><dt className="text-muted">{name}</dt><dd className="shrink-0 font-bold">{money(amount)}</dd></div>)}</dl>}</Card>)}</section>
    <OrdersCard orders={orders} open={ordersOpen} setOpen={setOrdersOpen} openDetail={openDetail} />
    <Card className="grid gap-3 sm:grid-cols-3"><Metric label="Средний чек" value={money(orders.length ? totals.revenue / orders.length : 0)} /><Metric label="Средняя прибыль" value={money(orders.length ? totals.profit / orders.length : 0)} /><Metric label="Маржинальность" value={`${margin}%`} /></Card>
  </>;
}

function Analytics({ totals, previous, change, margin, chart, orders }: { totals: ReturnType<typeof calculateFinance>; previous: ReturnType<typeof calculateFinance>; change: number | null; margin: number; chart: DailyFinance[]; orders: Order[] }) {
  const profitChange = percentChange(totals.profit, previous.profit);
  const averageCheck = totals.count ? totals.revenue / totals.count : 0;
  const previousAverageCheck = previous.count ? previous.revenue / previous.count : 0;
  const averageChange = percentChange(averageCheck, previousAverageCheck);
  return <div className="grid gap-4">
    <section className="grid grid-cols-2 gap-2 lg:grid-cols-4">
      <AnalyticsMetric label="Выручка" value={money(totals.revenue)} change={change} values={chart.map((item) => item.revenue)} color="#4f7cff" />
      <AnalyticsMetric label="Прибыль" value={money(totals.profit)} change={profitChange} values={chart.map((item) => item.profit)} color="#ffd600" />
      <AnalyticsMetric label="Средний чек" value={money(averageCheck)} change={averageChange} values={chart.map((item) => item.orders ? item.revenue / item.orders : 0)} color="#35d39a" />
      <AnalyticsMetric label="Маржинальность" value={`${margin}%`} hint={`${totals.count} завершённых заказов`} values={chart.map((item) => item.revenue ? item.profit / item.revenue * 100 : 0)} color="#9b6cff" />
    </section>
    <PerformanceChart items={chart} total={totals.revenue} />
    <section className="grid gap-4 lg:grid-cols-[1.05fr_1.35fr]">
      <RevenueDonut totals={totals} />
      <RevenueDirections totals={totals} />
    </section>
    <section className="grid gap-4 lg:grid-cols-2">
      <Card className="border-line/80 bg-gradient-to-br from-panel to-panel-soft"><h2 className="text-base font-black">Что изменилось</h2><div className="mt-3 grid gap-2"><ChangeRow label="Выручка" value={change} /><ChangeRow label="Прибыль" value={profitChange} /><ChangeRow label="Средний чек" value={averageChange} /><ChangeRow label="Маржинальность" value={margin} suffix="% сейчас" neutral /></div></Card>
      <WorkRevenueDirections orders={orders} />
    </section>
  </div>;
}

type DailyFinance = { label: string; revenue: number; profit: number; labor: number; parts: number; orders: number };

function AnalyticsMetric({ label, value, change, hint, values, color }: { label: string; value: string; change?: number | null; hint?: string; values: number[]; color: string }) { return <Card className="min-w-0 border-line/80 bg-gradient-to-br from-panel to-panel-soft p-3 sm:p-4"><div className="flex items-start justify-between gap-2"><p className="text-xs font-bold text-muted sm:text-sm">{label}</p>{change !== undefined && change !== null && <span className={`text-[11px] font-black ${change >= 0 ? "text-success" : "text-danger"}`}>{change >= 0 ? "+" : ""}{change}%</span>}</div><strong className="mt-1 block truncate text-lg font-black sm:text-2xl">{value}</strong><p className="mt-1 truncate text-[10px] text-muted sm:text-xs">{hint ?? "к прошлому периоду"}</p><Sparkline values={values} color={color} /></Card>; }

function Sparkline({ values, color }: { values: number[]; color: string }) { const width = 150; const height = 34; const min = Math.min(...values, 0); const max = Math.max(...values, 1); const range = Math.max(max - min, 1); const points = values.map((value, index) => `${values.length === 1 ? width / 2 : index / Math.max(values.length - 1, 1) * width},${height - 3 - (value - min) / range * (height - 7)}`).join(" "); return <svg className="mt-2 h-8 w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id={`spark-${color.replace("#", "")}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".28" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>{points && <><polygon points={`0,${height} ${points} ${width},${height}`} fill={`url(#spark-${color.replace("#", "")})`} /><polyline points={points} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" /></>}</svg>; }

function PerformanceChart({ items, total }: { items: DailyFinance[]; total: number }) { const width = 760; const height = 248; const left = 48; const right = 12; const top = 14; const bottom = 30; const plotWidth = width - left - right; const plotHeight = height - top - bottom; const values = items.flatMap((item) => [item.revenue, item.profit]); const min = Math.min(0, ...values); const max = Math.max(1, ...values); const range = Math.max(max - min, 1); const y = (value: number) => top + (max - value) / range * plotHeight; const line = (key: "revenue" | "profit") => items.map((item, index) => `${left + (items.length <= 1 ? plotWidth / 2 : index / (items.length - 1) * plotWidth)},${y(item[key])}`).join(" "); const revenueLine = line("revenue"); const profitLine = line("profit"); const labelEvery = Math.max(1, Math.ceil(items.length / 7)); return <Card className="overflow-hidden border-info/20 bg-gradient-to-br from-panel to-[#111a26]"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-black">Динамика бизнеса</h2><p className="mt-1 text-sm text-muted">Выручка и прибыль по дням</p></div><div className="text-right"><strong className="block text-xl">{money(total)}</strong><span className="text-xs text-muted">общая выручка</span></div></div><div className="mt-3 rounded-xl border border-line/70 bg-canvas/45 p-2"><svg className="h-auto w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="График выручки и прибыли">{[0, .25, .5, .75, 1].map((tick) => { const value = min + range * tick; const lineY = y(value); return <g key={tick}><line x1={left} y1={lineY} x2={width - right} y2={lineY} stroke="#253241" strokeWidth="1" /><text x={left - 8} y={lineY + 4} textAnchor="end" fill="#768596" fontSize="10">{formatCompact(value)}</text></g>; })}{items.length > 0 && <polygon points={`${left},${y(0)} ${revenueLine} ${width - right},${y(0)}`} fill="#4f7cff18" />}{items.length > 0 && <polyline points={revenueLine} fill="none" stroke="#4f7cff" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />}{items.length > 0 && <polyline points={profitLine} fill="none" stroke="#ffd600" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />}{items.map((item, index) => (index % labelEvery === 0 || index === items.length - 1) && <text key={`${item.label}-${index}`} x={left + (items.length <= 1 ? plotWidth / 2 : index / (items.length - 1) * plotWidth)} y={height - 8} textAnchor="middle" fill="#8391a2" fontSize="10">{item.label}</text>)}</svg></div><div className="mt-3 flex gap-5 text-xs text-muted"><span className="flex items-center gap-2"><i className="h-0.5 w-5 bg-info" />Выручка</span><span className="flex items-center gap-2"><i className="h-0.5 w-5 bg-apex" />Прибыль</span></div></Card>; }

function RevenueDonut({ totals }: { totals: ReturnType<typeof calculateFinance> }) { const earnings = totals.labor + totals.markup; const laborPercent = earnings > 0 ? Math.round(totals.labor / earnings * 100) : 0; const partsProfitPercent = Math.max(0, 100 - laborPercent); return <Card className="border-line/80 bg-gradient-to-br from-panel to-panel-soft"><div className="flex items-center justify-between"><h2 className="text-base font-black">Структура заработка</h2><span className="text-xs text-muted">Чистая прибыль</span></div><div className="mt-4 flex items-center gap-5"><div className="grid size-32 shrink-0 place-items-center rounded-full" style={{ background: `conic-gradient(#4f7cff 0 ${laborPercent}%, #ffd600 ${laborPercent}% 100%)` }}><div className="grid size-[92px] place-items-center rounded-full bg-panel text-center"><span><strong className="block text-base">{money(earnings)}</strong><small className="text-muted">заработок</small></span></div></div><dl className="min-w-0 flex-1 space-y-3 text-sm"><LegendRow color="bg-info" label="Работы" percent={laborPercent} value={totals.labor} /><LegendRow color="bg-apex" label="Прибыль с запчастей" percent={partsProfitPercent} value={totals.markup} /></dl></div></Card>; }

function LegendRow({ color, label, percent, value }: { color: string; label: string; percent?: number; value: number }) { return <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2"><span className={`size-2 rounded-full ${color}`} /><dt className="break-words text-muted">{label}{percent !== undefined ? ` · ${percent}%` : ""}</dt><dd className="whitespace-nowrap font-bold">{money(value)}</dd></div>; }

function RevenueDirections({ totals }: { totals: ReturnType<typeof calculateFinance> }) { const rows = [{ label: "Работы", value: totals.labor, color: "bg-info" }, { label: "Продажа запчастей", value: totals.partsRevenue, color: "bg-success" }, { label: "Прибыль с запчастей", value: totals.markup, color: "bg-apex" }, { label: "Закупка запчастей", value: totals.partsCost, color: "bg-purple-400" }]; const max = Math.max(...rows.map((row) => row.value), 1); return <Card className="border-line/80 bg-gradient-to-br from-panel to-panel-soft"><div className="flex items-center justify-between"><h2 className="text-base font-black">Доход по направлениям</h2><span className="text-xs text-muted">₽ за период</span></div><div className="mt-5 grid gap-4">{rows.map((row) => <div key={row.label}><div className="mb-1.5 flex justify-between gap-3 text-xs"><span className="text-muted">{row.label}</span><strong>{money(row.value)}</strong></div><div className="h-2 overflow-hidden rounded-full bg-canvas"><div className={`h-full rounded-full ${row.color}`} style={{ width: `${Math.max(row.value ? 4 : 0, row.value / max * 100)}%` }} /></div></div>)}</div></Card>; }

type WorkRevenueRow = { label: string; value: number; color: string };
const workGroups: Array<WorkRevenueRow & { pattern: RegExp }> = [
  { label: "Тормозная система", value: 0, color: "bg-danger", pattern: /тормоз|колод|диск|барабан|суппорт|ручник/i },
  { label: "ТО и масла", value: 0, color: "bg-apex", pattern: /то\b|масл|фильтр|жидкост|антифриз|свеч/i },
  { label: "Ходовая часть", value: 0, color: "bg-info", pattern: /ходов|подвес|амортиз|стойк|пружин|рычаг|сайлент|шаров|тяга|наконеч|ступиц|подшип|гранат/i },
  { label: "Двигатель", value: 0, color: "bg-success", pattern: /двигател|мотор|гбц|грм|ремень|цепь|турбин|форсунк|компресс|прокладк|сальник/i },
  { label: "Электрика", value: 0, color: "bg-purple-400", pattern: /электр|провод|ламп|генератор|стартер|аккум|датчик|блок|бензонасос/i },
  { label: "Кузов и салон", value: 0, color: "bg-pink-400", pattern: /кузов|двер|стекл|бампер|покрас|салон|сиден|замок/i },
];

function workRevenueRows(orders: Order[]): WorkRevenueRow[] {
  const totals = new Map(workGroups.map((group) => [group.label, 0]));
  totals.set("Прочие работы", 0);
  for (const order of orders) {
    if (!order.labor_revenue || !order.description.trim()) continue;
    const lines = order.description.split(/(?:\r?\n|;\s*)+/).flatMap((line) => line.split(/\s+(?=(?:замена|ремонт|установка|диагностика|регулировка|обслуживание|снятие|покраска)\b)/iu)).filter(Boolean);
    const groups = [...new Set(lines.map((line) => workGroups.find((group) => group.pattern.test(line))?.label ?? "Прочие работы"))];
    for (const group of groups) totals.set(group, (totals.get(group) ?? 0) + order.labor_revenue / groups.length);
  }
  return [...workGroups.map(({ label, color }) => ({ label, color, value: totals.get(label) ?? 0 })), { label: "Прочие работы", color: "bg-muted", value: totals.get("Прочие работы") ?? 0 }].filter((row) => row.value > 0).sort((a, b) => b.value - a.value);
}

function WorkRevenueDirections({ orders }: { orders: Order[] }) {
  const rows = workRevenueRows(orders); const max = Math.max(...rows.map((row) => row.value), 1);
  return <Card className="border-line/80 bg-gradient-to-br from-panel to-panel-soft"><div className="flex items-center justify-between gap-3"><div><h2 className="text-base font-black">Доход по видам работ</h2><p className="mt-1 text-xs text-muted">Только оплата за выполненные работы</p></div><span className="text-xs text-muted">₽ за период</span></div><div className="mt-5 grid gap-4">{rows.length ? rows.map((row) => <div key={row.label}><div className="mb-1.5 flex justify-between gap-3 text-xs"><span className="text-muted">{row.label}</span><strong>{money(Math.round(row.value))}</strong></div><div className="h-2 overflow-hidden rounded-full bg-canvas"><div className={`h-full rounded-full ${row.color}`} style={{ width: `${Math.max(4, row.value / max * 100)}%` }} /></div></div>) : <p className="rounded-xl bg-canvas/60 p-3 text-sm text-muted">Добавьте выполненные работы в завершённые заказы — здесь появится разбивка.</p>}</div></Card>;
}

function ChangeRow({ label, value, suffix = "%", neutral = false }: { label: string; value: number | null; suffix?: string; neutral?: boolean }) { const shown = value === null ? "—" : `${!neutral && value >= 0 ? "+" : ""}${value}${suffix}`; return <div className="flex items-center justify-between rounded-xl bg-canvas/65 px-3 py-2 text-sm"><span className="text-muted">{label}</span><strong className={neutral || value === null ? "text-white" : value >= 0 ? "text-success" : "text-danger"}>{shown}</strong></div>; }

function percentChange(current: number, previous: number) { return previous ? Math.round((current - previous) / Math.abs(previous) * 100) : null; }

function formatCompact(value: number) { const absolute = Math.abs(value); const sign = value < 0 ? "−" : ""; if (absolute >= 1_000_000) return `${sign}${(absolute / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}м`; if (absolute >= 1_000) return `${sign}${Math.round(absolute / 1_000)}к`; return `${sign}${Math.round(absolute)}`; }

function OrdersCard({ orders, open, setOpen, openDetail }: { orders: Order[]; open: boolean; setOpen: (value: boolean) => void; openDetail: AppOutlet["openDetail"] }) { return <Card><button type="button" className="flex w-full flex-wrap items-center justify-between gap-3 text-left" onClick={() => setOpen(!open)}><div><h2 className="text-lg font-black">Заказы в расчёте</h2><p className="mt-1 text-sm text-muted">Подробная расшифровка каждой суммы</p></div><span className="flex items-center gap-2"><strong className="text-apex">{orders.length}</strong><ChevronDown className={`transition ${open ? "rotate-180" : ""}`} /></span></button>{open && <div className="mt-4 grid gap-2">{orders.length ? orders.map((item) => <button key={item.id} type="button" onClick={() => openDetail({ kind: "order", value: item })} className="grid min-w-0 gap-2 rounded-xl bg-panel-soft p-3 text-left transition hover:bg-line sm:grid-cols-[1fr_auto] sm:items-center"><div className="min-w-0"><p className="break-words font-bold">#{item.id} · {item.brand} {item.model}</p><p className="mt-1 break-words text-sm text-muted">{formatDateTime(item.completed_at || item.created_at)} · {item.description}</p></div><div className="grid grid-cols-2 gap-x-4 text-sm sm:text-right"><span className="text-muted">Выручка</span><strong>{money(item.labor_revenue + item.parts_revenue)}</strong><span className="text-muted">Прибыль</span><strong className="text-success">{money(item.profit)}</strong></div></button>) : <EmptyState>За выбранный период заказов нет</EmptyState>}</div>}</Card>; }
function Metric({ label, value, hint, positive }: { label: string; value: string; hint?: string; positive?: boolean }) { return <div className="rounded-xl bg-panel-soft p-4"><p className="text-sm text-muted">{label}</p><strong className="mt-1 block text-xl font-black">{value}</strong>{hint && <p className={`mt-1 text-xs ${positive === undefined ? "text-muted" : positive ? "text-success" : "text-danger"}`}>{hint}</p>}</div>; }
function dailyFinance(orders: Order[], days: number, end: Date): DailyFinance[] { const start = startOfDay(end); start.setDate(start.getDate() - (days - 1)); return Array.from({ length: days }, (_, index) => { const day = new Date(start); day.setDate(start.getDate() + index); const next = new Date(day); next.setDate(day.getDate() + 1); const dailyOrders = orders.filter((order) => { const date = parseCrmDate(order.completed_at!); return date >= day && date < next; }); return { label: days <= 7 ? day.toLocaleDateString("ru-RU", { weekday: "short" }).slice(0, 2) : String(day.getDate()), revenue: dailyOrders.reduce((sum, order) => sum + order.labor_revenue + order.parts_revenue, 0), profit: dailyOrders.reduce((sum, order) => sum + order.profit, 0), labor: dailyOrders.reduce((sum, order) => sum + order.labor_revenue, 0), parts: dailyOrders.reduce((sum, order) => sum + order.parts_revenue, 0), orders: dailyOrders.length }; }); }
