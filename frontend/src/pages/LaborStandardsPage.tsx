import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { BookOpen, Check, Clock3, Search, Wrench, X } from "lucide-react";
import { Button, Card, EmptyState, inputClass } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { money } from "../lib/format";
import { laborCategories, laborMarket, laborMarketCheckedAt, laborSources, laborStandards } from "../lib/laborStandards";
import { refreshCrm } from "../lib/query";
import { saveSettings, useAppSettings } from "../lib/settings";
import type { Order, OrderInput } from "../lib/types";
import { useCrm } from "../features/crm/useCrm";

const RECENT_KEY = "apex-labor-recent-operations";
const LAST_ORDER_KEY = "apex-labor-last-order";
const readRecent = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]") as unknown;
    return Array.isArray(saved) ? saved.filter((item): item is string => typeof item === "string") : [];
  } catch { return []; }
};
const orderPayload = (order: Order, description: string, laborRevenue: number): OrderInput => ({
  car_id: order.car_id, description, labor_revenue: laborRevenue, parts_cost: order.parts_cost,
  parts_revenue: order.parts_revenue, parts_profit: order.parts_profit, concern: order.concern,
  agreed_amount: order.agreed_amount, recommendations: order.recommendations, parts_source: order.parts_source,
  mileage_at_visit: order.mileage_at_visit,
});
const marketRange = (minimum: number, maximum: number) => minimum === maximum ? money(minimum) : `${money(minimum)}–${money(maximum)}`;

export function LaborStandardsPage() {
  const crm = useCrm(); const settings = useAppSettings();
  const [query, setQuery] = useState(""); const [category, setCategory] = useState<string>("all");
  const [selectedId, setSelectedId] = useState(laborStandards[0]!.id); const [hours, setHours] = useState(laborStandards[0]!.hours);
  const [priceMode, setPriceMode] = useState<"market" | "rate">("rate"); const [orderId, setOrderId] = useState(() => localStorage.getItem(LAST_ORDER_KEY) ?? "");
  const [saved, setSaved] = useState(false); const [mobileOpen, setMobileOpen] = useState(false); const [recentIds, setRecentIds] = useState(readRecent);
  const selected = laborStandards.find((item) => item.id === selectedId) ?? laborStandards[0]!;
  const market = laborMarket[selected.id]; const ratePrice = Math.round(hours * settings.laborHourRate / 50) * 50;
  const marketPrice = market ? Math.min(market.priceMax, Math.max(market.priceMin, ratePrice)) : ratePrice;
  const price = priceMode === "market" && market ? marketPrice : ratePrice;
  const orders = useMemo(() => (crm.data?.orders ?? []).filter((order) => !order.archived_at && !["ready", "completed"].includes(order.status)), [crm.data?.orders]);
  const effectiveOrderId = orders.some((order) => String(order.id) === orderId) ? orderId : orders.length === 1 ? String(orders[0]!.id) : "";
  const filtered = useMemo(() => laborStandards.filter((item) => {
    const needle = query.trim().toLocaleLowerCase("ru-RU");
    return (category === "all" || item.category === category) && (!needle || `${item.name} ${item.category} ${item.applicability}`.toLocaleLowerCase("ru-RU").includes(needle));
  }), [category, query]);
  const recent = recentIds.map((id) => laborStandards.find((item) => item.id === id)).filter((item): item is typeof laborStandards[number] => Boolean(item));

  const add = useMutation({
    mutationFn: async () => {
      const order = orders.find((item) => String(item.id) === effectiveOrderId);
      if (!order) throw new Error("Выберите активный заказ-наряд");
      const existingLines = order.description.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      if (existingLines.some((line) => line.toLocaleLowerCase("ru-RU") === selected.name.toLocaleLowerCase("ru-RU"))) throw new Error("Эта работа уже есть в выбранном заказе");
      return api.saveOrder(orderPayload(order, [...existingLines, selected.name].join("\n"), order.labor_revenue + price), order.id);
    },
    onSuccess: async () => { await refreshCrm(); setSaved(true); window.setTimeout(() => { setSaved(false); setMobileOpen(false); }, 1400); },
  });
  const select = (id: string, openMobile = true) => {
    const operation = laborStandards.find((item) => item.id === id); if (!operation) return;
    setSelectedId(id); setHours(operation.hours); setPriceMode("rate"); setSaved(false);
    const next = [id, ...recentIds.filter((value) => value !== id)].slice(0, 8); setRecentIds(next); localStorage.setItem(RECENT_KEY, JSON.stringify(next));
    if (openMobile) setMobileOpen(true);
  };
  const selectOrder = (value: string) => { setOrderId(value); localStorage.setItem(LAST_ORDER_KEY, value); setSaved(false); };
  const saveRate = (value: number) => { setSaved(false); saveSettings({ ...settings, laborHourRate: Math.max(0, value) }); };
  const addLabel = add.isPending ? "Добавляю…" : saved ? "Добавлено в заказ" : "Добавить в заказ";

  return <div className="grid gap-5 pb-24 xl:pb-0">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm font-bold text-apex">СПРАВОЧНИК APEX AUTO</p><h1 className="mt-1 text-3xl font-black">Нормы времени</h1><p className="mt-1 text-muted">Рабочие нормы Apex и открытые цены сервисов России, проверенные в 2026 году.</p></div><label className="w-full sm:w-56"><span className="mb-1 block text-xs font-bold text-muted">Стоимость нормо-часа</span><div className="relative"><input className={`${inputClass} pr-10`} type="number" min="0" step="50" value={settings.laborHourRate} onChange={(event) => saveRate(Number(event.target.value))} /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">₽</span></div></label></header>
    <section className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_240px]"><label className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={18}/><input className={`${inputClass} pl-10`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поиск: масло, колодки, амортизатор…" /></label><select className={inputClass} value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">Все разделы</option>{laborCategories.map((item) => <option key={item}>{item}</option>)}</select></section>
    {recent.length > 0 && <section className="xl:hidden"><p className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Недавние работы</p><div className="flex gap-2 overflow-x-auto pb-1">{recent.map((item) => <button key={item.id} type="button" onClick={() => select(item.id)} className="shrink-0 rounded-xl border border-line bg-panel-soft px-3 py-2 text-left text-sm font-bold transition hover:border-apex/60"><span className="block max-w-52 truncate">{item.name}</span><small className="text-apex">{item.hours.toLocaleString("ru-RU")} н/ч</small></button>)}</div></section>}
    <section className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(330px,.75fr)]">
      <Card className="overflow-hidden p-0"><div className="flex items-center justify-between border-b border-line px-4 py-3"><h2 className="font-black">Операции</h2><span className="rounded-full bg-apex/10 px-2 py-1 text-xs font-bold text-apex">{filtered.length}</span></div>{filtered.length ? <div className="divide-y divide-line">{filtered.map((item) => { const reference = laborMarket[item.id]; return <button key={item.id} type="button" onClick={() => select(item.id)} className={`grid w-full gap-1 px-4 py-3 text-left transition sm:grid-cols-[minmax(0,1fr)_100px_150px] sm:items-center ${selectedId === item.id ? "bg-info/10" : "hover:bg-panel-soft"}`}><span className="min-w-0"><strong className="block break-words">{item.name}</strong><small className="text-muted">{item.category} · {item.applicability}</small></span><span className="font-black text-apex">{item.hours.toLocaleString("ru-RU")} н/ч</span><span><b className="block">{reference ? marketRange(reference.priceMin, reference.priceMax) : money(Math.round(item.hours * settings.laborHourRate / 50) * 50)}</b><small className="text-muted">{reference ? "рынок России" : "по нормо-часу"}</small></span></button>; })}</div> : <EmptyState>По вашему запросу операций не найдено</EmptyState>}</Card>
      <Card className="hidden h-fit border-apex/20 xl:sticky xl:top-20 xl:block"><div className="grid size-11 place-items-center rounded-xl bg-apex/10 text-apex"><Clock3 /></div><h2 className="mt-4 text-xl font-black">{selected.name}</h2><p className="mt-1 text-sm text-muted">{selected.category} · {selected.applicability} · {selected.unit}</p><dl className="mt-5 divide-y divide-line text-sm"><div className="flex items-center justify-between gap-3 py-3"><dt className="text-muted">Рабочая норма Apex</dt><dd className="w-28"><input aria-label="Норма времени" className={`${inputClass} py-2 text-right font-bold`} type="number" min="0.1" step="0.1" value={hours} onChange={(event) => { setHours(Math.max(.1, Number(event.target.value))); setSaved(false); }} /></dd></div>{market?.publicHoursMin && <div className="flex justify-between gap-3 py-3"><dt className="text-muted">Открытая длительность</dt><dd className="font-bold text-info">от {market.publicHoursMin.toLocaleString("ru-RU")} ч</dd></div>}<div className="flex justify-between gap-3 py-3"><dt className="text-muted">Расчёт по ставке</dt><dd className="font-bold">{money(ratePrice)}</dd></div>{market && <div className="flex justify-between gap-3 py-3"><dt className="text-muted">Публичные цены по России</dt><dd className="text-right font-bold text-success">{marketRange(market.priceMin, market.priceMax)}</dd></div>}</dl>{market && <div className="mt-4 grid grid-cols-2 gap-2 rounded-xl bg-panel-soft p-1"><button type="button" className={`rounded-lg px-2 py-2 text-xs font-bold ${priceMode === "market" ? "bg-apex text-black" : "text-muted"}`} onClick={() => { setPriceMode("market"); setSaved(false); }}>По рынку · {money(marketPrice)}</button><button type="button" className={`rounded-lg px-2 py-2 text-xs font-bold ${priceMode === "rate" ? "bg-apex text-black" : "text-muted"}`} onClick={() => { setPriceMode("rate"); setSaved(false); }}>По нормо-часу · {money(ratePrice)}</button></div>}<div className="mt-4 flex justify-between gap-3 rounded-xl border border-apex/30 bg-apex/5 p-3"><span className="text-sm text-muted">Цена в заказ</span><strong className="text-xl text-apex">{money(price)}</strong></div><OrderPicker orders={orders} orderId={effectiveOrderId} onChange={selectOrder}/><Button className="mt-3 w-full" disabled={!effectiveOrderId || add.isPending || saved} onClick={() => add.mutate()}>{saved ? <Check size={18}/> : <Wrench size={18}/>} {addLabel}</Button>{add.error && <ErrorMessage error={add.error}/>}<Sources market={market}/></Card>
    </section>
    {mobileOpen && <div className="fixed inset-0 z-50 xl:hidden" role="dialog" aria-modal="true" aria-label="Добавление работы"><button type="button" className="absolute inset-0 bg-black/65" aria-label="Закрыть" onClick={() => setMobileOpen(false)} /><section className="absolute inset-x-0 bottom-0 max-h-[86dvh] overflow-y-auto rounded-t-3xl border border-line bg-panel p-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-2xl"><div className="mx-auto mb-4 h-1.5 w-12 rounded-full bg-muted/50"/><div className="flex items-start gap-3"><span className="grid size-11 shrink-0 place-items-center rounded-xl bg-apex/10 text-apex"><Clock3 /></span><div className="min-w-0 flex-1"><h2 className="break-words text-lg font-black">{selected.name}</h2><p className="mt-1 text-sm text-muted">{selected.category} · по умолчанию {selected.hours.toLocaleString("ru-RU")} н/ч</p></div><button type="button" className="grid size-10 place-items-center rounded-xl bg-panel-soft text-muted" aria-label="Закрыть" onClick={() => setMobileOpen(false)}><X size={20}/></button></div><label className="mt-4 block rounded-xl border border-line bg-panel-soft p-3"><span className="mb-2 block text-xs font-bold text-muted">Нормо-часы для этого заказа</span><div className="flex items-center gap-2"><button type="button" className="grid size-10 shrink-0 place-items-center rounded-lg border border-line text-lg font-black text-muted" aria-label="Уменьшить нормо-часы" onClick={() => { setHours((value) => Math.max(.1, Math.round((value - .1) * 10) / 10)); setSaved(false); }}>−</button><input aria-label="Норма времени" className={`${inputClass} min-w-0 py-2 text-center font-black`} type="number" min="0.1" step="0.1" inputMode="decimal" value={hours} onChange={(event) => { const value = Number(event.target.value); setHours(Number.isFinite(value) ? Math.max(.1, value) : .1); setSaved(false); }} /><span className="shrink-0 text-sm font-bold text-muted">н/ч</span><button type="button" className="grid size-10 shrink-0 place-items-center rounded-lg border border-line text-lg font-black text-apex" aria-label="Увеличить нормо-часы" onClick={() => { setHours((value) => Math.round((value + .1) * 10) / 10); setSaved(false); }}>+</button></div><p className="mt-2 text-xs text-muted">Изменение действует только для добавляемой работы и сразу пересчитывает цену.</p></label><div className="mt-4 grid grid-cols-2 gap-2 rounded-xl bg-panel-soft p-1"><button type="button" className={`rounded-lg px-2 py-2 text-xs font-bold ${priceMode === "rate" ? "bg-apex text-black" : "text-muted"}`} onClick={() => { setPriceMode("rate"); setSaved(false); }}>По нормо-часу<br/>{money(ratePrice)}</button>{market ? <button type="button" className={`rounded-lg px-2 py-2 text-xs font-bold ${priceMode === "market" ? "bg-apex text-black" : "text-muted"}`} onClick={() => { setPriceMode("market"); setSaved(false); }}>По рынку<br/>{money(marketPrice)}</button> : <div className="grid place-items-center text-xs text-muted">Рыночной цены нет</div>}</div><div className="mt-3 flex justify-between rounded-xl border border-apex/30 bg-apex/5 p-3"><span className="text-sm text-muted">Добавится в заказ</span><strong className="text-xl text-apex">{money(price)}</strong></div><OrderPicker orders={orders} orderId={effectiveOrderId} onChange={selectOrder}/><Button className="mt-3 w-full min-h-12" disabled={!effectiveOrderId || add.isPending || saved} onClick={() => add.mutate()}>{saved ? <Check size={18}/> : <Wrench size={18}/>} {addLabel}</Button>{!orders.length && <p className="mt-3 rounded-xl bg-panel-soft p-3 text-sm text-muted">Сначала создайте или откройте заказ-наряд.</p>}{add.error && <ErrorMessage error={add.error}/>}</section></div>}
  </div>;
}

function OrderPicker({ orders, orderId, onChange }: { orders: Order[]; orderId: string; onChange: (value: string) => void }) {
  return <label className="mt-4 block"><span className="mb-1 block text-xs font-bold text-muted">Добавить в заказ-наряд</span><select className={inputClass} value={orderId} onChange={(event) => onChange(event.target.value)}><option value="">Выберите активный заказ</option>{orders.map((order) => <option key={order.id} value={order.id}>№{order.id} · {order.brand} {order.model}</option>)}</select></label>;
}
function Sources({ market }: { market: typeof laborMarket[string] }) {
  if (!market) return <p className="mt-4 flex gap-2 rounded-xl bg-panel-soft p-3 text-xs text-muted"><BookOpen className="shrink-0 text-info" size={18}/>Рабочая норма Apex редактируется с учётом модели, доступа к узлу и состояния крепежа.</p>;
  return <div className="mt-4 rounded-xl border border-line p-3"><p className="text-xs font-bold uppercase text-muted">Источники · проверено {laborMarketCheckedAt}</p><div className="mt-2 flex flex-wrap gap-2">{market.sourceIds.map((id) => <a key={id} href={laborSources[id].url} target="_blank" rel="noreferrer" className="rounded-lg bg-info/10 px-2 py-1 text-xs font-bold text-info hover:bg-info/20">{laborSources[id].title}</a>)}</div></div>;
}
function ErrorMessage({ error }: { error: unknown }) { return <p className="mt-3 rounded-xl bg-danger/10 p-3 text-sm text-danger">{error instanceof ApiError || error instanceof Error ? error.message : "Не удалось добавить работу"}</p>; }
