import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { BookOpen, Check, Clock3, Search, Wrench } from "lucide-react";
import { Button, Card, EmptyState, inputClass } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { money } from "../lib/format";
import { laborCategories, laborStandards } from "../lib/laborStandards";
import { refreshCrm } from "../lib/query";
import { saveSettings, useAppSettings } from "../lib/settings";
import type { Order, OrderInput } from "../lib/types";
import { useCrm } from "../features/crm/useCrm";

const orderPayload = (order: Order, description: string, laborRevenue: number): OrderInput => ({
  car_id: order.car_id,
  description,
  labor_revenue: laborRevenue,
  parts_cost: order.parts_cost,
  parts_revenue: order.parts_revenue,
  parts_profit: order.parts_profit,
  concern: order.concern,
  agreed_amount: order.agreed_amount,
  recommendations: order.recommendations,
  parts_source: order.parts_source,
  mileage_at_visit: order.mileage_at_visit,
});

export function LaborStandardsPage() {
  const crm = useCrm();
  const settings = useAppSettings();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("all");
  const [selectedId, setSelectedId] = useState(laborStandards[0]!.id);
  const [hours, setHours] = useState(laborStandards[0]!.hours);
  const [orderId, setOrderId] = useState("");
  const [saved, setSaved] = useState(false);
  const selected = laborStandards.find((item) => item.id === selectedId) ?? laborStandards[0]!;
  const price = Math.round(hours * settings.laborHourRate / 50) * 50;
  const orders = useMemo(() => (crm.data?.orders ?? []).filter((order) => !order.archived_at && !["ready", "completed"].includes(order.status)), [crm.data?.orders]);
  const filtered = useMemo(() => laborStandards.filter((item) => {
    const matchesCategory = category === "all" || item.category === category;
    const needle = query.trim().toLocaleLowerCase("ru-RU");
    return matchesCategory && (!needle || `${item.name} ${item.category} ${item.applicability}`.toLocaleLowerCase("ru-RU").includes(needle));
  }), [category, query]);
  const add = useMutation({
    mutationFn: async () => {
      const order = orders.find((item) => String(item.id) === orderId);
      if (!order) throw new Error("Выберите заказ-наряд");
      const work = selected.name;
      const existingLines = order.description.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      if (existingLines.some((line) => line.toLocaleLowerCase("ru-RU") === work.toLocaleLowerCase("ru-RU"))) throw new Error("Эта работа уже есть в выбранном заказе");
      const description = [...existingLines, work].join("\n");
      return api.saveOrder(orderPayload(order, description, order.labor_revenue + price), order.id);
    },
    onSuccess: async () => { await refreshCrm(); setSaved(true); window.setTimeout(() => setSaved(false), 1800); },
  });
  const select = (id: string) => {
    const operation = laborStandards.find((item) => item.id === id);
    if (!operation) return;
    setSelectedId(id); setHours(operation.hours); setSaved(false);
  };
  const saveRate = (value: number) => { setSaved(false); saveSettings({ ...settings, laborHourRate: Math.max(0, value) }); };

  return <div className="grid gap-5">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-sm font-bold text-apex">СПРАВОЧНИК APEX AUTO</p><h1 className="mt-1 text-3xl font-black">Нормы времени</h1><p className="mt-1 text-muted">Стартовые нормы для расчёта работ. Проверяйте их по фактическому времени вашего сервиса.</p></div><label className="w-full sm:w-56"><span className="mb-1 block text-xs font-bold text-muted">Стоимость нормо-часа</span><div className="relative"><input className={`${inputClass} pr-10`} type="number" min="0" step="50" value={settings.laborHourRate} onChange={(event) => saveRate(Number(event.target.value))} /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-muted">₽</span></div></label></header>
    <section className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_240px]"><label className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={18}/><input className={`${inputClass} pl-10`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поиск: масло, колодки, амортизатор…" /></label><select className={inputClass} value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">Все разделы</option>{laborCategories.map((item) => <option key={item}>{item}</option>)}</select></section>
    <section className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(330px,.75fr)]">
      <Card className="overflow-hidden p-0"><div className="flex items-center justify-between border-b border-line px-4 py-3"><h2 className="font-black">Операции</h2><span className="rounded-full bg-apex/10 px-2 py-1 text-xs font-bold text-apex">{filtered.length}</span></div>{filtered.length ? <div className="divide-y divide-line">{filtered.map((item) => <button key={item.id} type="button" onClick={() => select(item.id)} className={`grid w-full gap-1 px-4 py-3 text-left transition sm:grid-cols-[minmax(0,1fr)_100px_110px] sm:items-center ${selectedId === item.id ? "bg-info/10" : "hover:bg-panel-soft"}`}><span className="min-w-0"><strong className="block break-words">{item.name}</strong><small className="text-muted">{item.category} · {item.applicability}</small></span><span className="font-black text-apex">{item.hours.toLocaleString("ru-RU")} н/ч</span><span className="font-bold">{money(Math.round(item.hours * settings.laborHourRate / 50) * 50)}</span></button>)}</div> : <EmptyState>По вашему запросу операций не найдено</EmptyState>}</Card>
      <Card className="h-fit border-apex/20 xl:sticky xl:top-20"><div className="grid size-11 place-items-center rounded-xl bg-apex/10 text-apex"><Clock3 /></div><h2 className="mt-4 text-xl font-black">{selected.name}</h2><p className="mt-1 text-sm text-muted">{selected.category} · {selected.applicability} · {selected.unit}</p><dl className="mt-5 divide-y divide-line text-sm"><div className="flex items-center justify-between gap-3 py-3"><dt className="text-muted">Норма времени</dt><dd className="w-28"><input aria-label="Норма времени" className={`${inputClass} py-2 text-right font-bold`} type="number" min="0.1" step="0.1" value={hours} onChange={(event) => { setHours(Math.max(.1, Number(event.target.value))); setSaved(false); }} /></dd></div><div className="flex justify-between gap-3 py-3"><dt className="text-muted">Ставка</dt><dd className="font-bold">{money(settings.laborHourRate)} / н/ч</dd></div><div className="flex justify-between gap-3 py-3"><dt className="text-muted">Расчётная цена</dt><dd className="text-lg font-black text-apex">{money(price)}</dd></div></dl><label className="mt-4 block"><span className="mb-1 block text-xs font-bold text-muted">Добавить в заказ-наряд</span><select className={inputClass} value={orderId} onChange={(event) => { setOrderId(event.target.value); setSaved(false); }}><option value="">Выберите активный заказ</option>{orders.map((order) => <option key={order.id} value={order.id}>№{order.id} · {order.brand} {order.model}</option>)}</select></label><Button className="mt-3 w-full" disabled={!orderId || add.isPending || saved} onClick={() => add.mutate()}>{saved ? <Check size={18}/> : <Wrench size={18}/>} {add.isPending ? "Добавляю…" : saved ? "Добавлено в заказ" : "Добавить работу и стоимость"}</Button>{add.error && <p className="mt-3 rounded-xl bg-danger/10 p-3 text-sm text-danger">{add.error instanceof ApiError || add.error instanceof Error ? add.error.message : "Не удалось добавить работу"}</p>}<p className="mt-4 flex gap-2 rounded-xl bg-panel-soft p-3 text-xs text-muted"><BookOpen className="shrink-0 text-info" size={18}/>Нормы стартовые, не являются официальным каталогом производителя. Изменение часов перед добавлением влияет только на выбранный заказ.</p></Card>
    </section>
  </div>;
}
