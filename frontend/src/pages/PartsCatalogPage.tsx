import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Download, PackageSearch, Search, ShoppingCart, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Card, EmptyState, inputClass, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { queryClient } from "../lib/query";
import type { ProfitLigaOrder, RosskoOrder, SupplierOffer } from "../lib/types";
import { useCrm } from "../features/crm/useCrm";

export function PartsCatalogPage() {
  const [params] = useSearchParams();
  const initialQuery = params.get("q")?.trim() ?? "";
  const preferredOrderId = Number(params.get("order_id") || 0);
  const crm = useCrm();
  const status = useQuery({ queryKey: ["parts-catalog-status"], queryFn: api.partsCatalogStatus });
  const [query, setQuery] = useState(initialQuery);
  const [submitted, setSubmitted] = useState(initialQuery.length >= 3 ? initialQuery : "");
  const [activeSupplier, setActiveSupplier] = useState<"rossko" | "profit_liga">("rossko");
  const [markup, setMarkup] = useState<number | null>(null);
  const effectiveMarkup = markup ?? status.data?.default_markup_percent ?? 40;
  const search = useQuery({ queryKey: ["parts-catalog", activeSupplier, submitted, effectiveMarkup], queryFn: () => api.searchParts(submitted, effectiveMarkup, activeSupplier), enabled: submitted.length >= 3, retry: false });
  const rosskoOrders = useQuery({ queryKey: ["rossko-orders", preferredOrderId], queryFn: () => api.rosskoOrders(preferredOrderId), enabled: activeSupplier === "rossko" && preferredOrderId > 0 && Boolean(status.data?.suppliers.rossko), retry: false });
  const profitOrders = useQuery({ queryKey: ["profit-orders", preferredOrderId], queryFn: () => api.profitLigaOrders(preferredOrderId), enabled: activeSupplier === "profit_liga" && preferredOrderId > 0 && Boolean(status.data?.suppliers.profit_liga), retry: false });
  const activeOrders = useMemo(() => crm.data?.orders.filter((order) => order.status === "in_progress") ?? [], [crm.data]);

  if (status.isPending || crm.isPending) return <Spinner label="Открываю каталог…" />;
  return <div className="grid gap-4">
    <header><p className="text-sm font-bold text-apex">Запчасти</p><h1 className="text-2xl font-black sm:text-3xl">Проценка и импорт заказов</h1><p className="mt-1 text-sm text-muted">Выберите поставщика — поиск и готовые заказы отображаются отдельно.</p></header>
    <Card>
      <form className="grid gap-3 sm:grid-cols-[1fr_auto]" onSubmit={(event) => { event.preventDefault(); if (query.trim().length >= 3) setSubmitted(query.trim()); }}>
        <div className="relative"><Search className="absolute left-4 top-1/2 -translate-y-1/2 text-muted" size={19} /><input className={`${inputClass} pl-11`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Введите точный артикул, например 26300" autoFocus /></div>
        <Button type="submit" disabled={query.trim().length < 3 || search.isFetching}>{search.isFetching ? "Ищу…" : "Найти"}</Button>
      </form>
      <div className="mt-4 flex flex-wrap items-center gap-3"><SlidersHorizontal size={18} className="text-apex" /><label className="flex items-center gap-2 text-sm text-muted">Наценка <input className="w-24 rounded-lg border border-line bg-canvas px-3 py-2 text-white" type="number" min="0" max="300" value={effectiveMarkup} onChange={(event) => setMarkup(Number(event.target.value))} />%</label><span className="rounded-lg bg-panel-soft px-3 py-2 text-sm text-muted">Цена округляется вверх до 50 ₽</span><Supplier name="ROSSKO" connected={status.data?.suppliers.rossko ?? false} /><Supplier name="Profit Liga" connected={status.data?.suppliers.profit_liga ?? false} /></div>
    </Card>
    <div className="grid grid-cols-2 gap-2 rounded-2xl border border-line bg-panel p-2">
      <button type="button" onClick={() => setActiveSupplier("rossko")} className={`min-h-12 rounded-xl px-3 font-bold transition ${activeSupplier === "rossko" ? "bg-apex text-black" : "bg-panel-soft text-muted hover:text-white"}`}>ROSSKO</button>
      <button type="button" onClick={() => setActiveSupplier("profit_liga")} className={`min-h-12 rounded-xl px-3 font-bold transition ${activeSupplier === "profit_liga" ? "bg-apex text-black" : "bg-panel-soft text-muted hover:text-white"}`}>Profit Liga</button>
    </div>
    {!status.data?.suppliers.rossko && !status.data?.suppliers.profit_liga && <Card className="border-apex/30 bg-apex/5"><p className="font-bold">Поставщики ещё не подключены</p><p className="mt-1 text-sm text-muted">Добавьте ключи ROSSKO и Profit Liga в настройки сервера. После этого цены и остатки появятся здесь автоматически.</p></Card>}
    {activeSupplier === "rossko" && preferredOrderId > 0 && status.data?.suppliers.rossko && <Card className="border-apex/40">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-black">Импорт готового заказа ROSSKO</h2><p className="mt-1 text-sm text-muted">Выберите заказ поставщика — все активные позиции попадут в заказ-наряд №{preferredOrderId} за одно нажатие.</p></div>{rosskoOrders.isFetching && <span className="text-sm text-muted">Обновляю…</span>}</div>
      {rosskoOrders.error && <p className="mt-3 text-sm text-danger">Не удалось получить последние заказы ROSSKO.</p>}
      <div className="mt-3 grid gap-2">{rosskoOrders.data?.orders.map((order) => <RosskoImport key={order.id} order={order} crmOrderId={preferredOrderId} markup={effectiveMarkup} />)}</div>
      {rosskoOrders.data && !rosskoOrders.data.orders.length && <p className="mt-3 text-sm text-muted">Последних заказов ROSSKO не найдено.</p>}
    </Card>}
    {activeSupplier === "profit_liga" && preferredOrderId > 0 && status.data?.suppliers.profit_liga && <Card className="border-apex/40">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-black">Импорт готового заказа Profit Liga</h2><p className="mt-1 text-sm text-muted">Все активные позиции выбранного заказа попадут в заказ-наряд №{preferredOrderId} за одно нажатие.</p></div>{profitOrders.isFetching && <span className="text-sm text-muted">Обновляю…</span>}</div>
      {profitOrders.error && <p className="mt-3 text-sm text-danger">Не удалось получить последние заказы Profit Liga.</p>}
      <div className="mt-3 grid gap-2">{profitOrders.data?.orders.map((order) => <ProfitImport key={order.id} order={order} crmOrderId={preferredOrderId} markup={effectiveMarkup} />)}</div>
      {profitOrders.data && !profitOrders.data.orders.length && <p className="mt-3 text-sm text-muted">Последних заказов Profit Liga не найдено.</p>}
    </Card>}
    {search.error && <Card className="border-danger/30 text-danger">Не удалось получить предложения поставщиков. Проверьте подключение и настройки API.</Card>}
    {search.data && <><div className="flex items-center justify-between"><h2 className="font-black">Предложения <span className="text-apex">{search.data.offers.length}</span></h2><span className="text-sm text-muted">Сначала выгодные</span></div>{search.data.offers.length ? <div className="grid gap-3">{search.data.offers.map((offer) => <Offer key={`${offer.supplier}-${offer.offer_id}`} offer={offer} orders={activeOrders.map((order) => ({ id: order.id, label: `№${order.id} · ${order.brand} ${order.model}` }))} preferredOrderId={preferredOrderId} />)}</div> : <EmptyState>По артикулу «{search.data.query}» предложений не найдено. Проверьте написание артикула без пробелов и лишних символов.</EmptyState>}</>}
    {!submitted && <EmptyState><PackageSearch className="mx-auto mb-3 text-apex" size={34} />Введите точный артикул. Поиск будет выполнен только у выбранного поставщика: {activeSupplier === "rossko" ? "ROSSKO" : "Profit Liga"}.</EmptyState>}
  </div>;
}

function RosskoImport({ order, crmOrderId, markup }: { order: RosskoOrder; crmOrderId: number; markup: number }) {
  const available = order.parts.filter((part) => ![7, 8, 9, 34, 35, 36].includes(part.status));
  const [selected, setSelected] = useState<string[]>(available.map((part) => part.article));
  const add = useMutation({
    mutationFn: () => api.importRosskoOrder(crmOrderId, order.id, markup, selected),
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["crm"] }), queryClient.invalidateQueries({ queryKey: ["rossko-orders", crmOrderId] })]);
    },
  });
  const unavailable = order.parts.length - available.length;
  return <div className="grid gap-3 rounded-xl border border-line bg-panel-soft p-3 sm:grid-cols-[1fr_auto] sm:items-center">
    <div><div className="flex flex-wrap items-center gap-2"><strong>ROSSKO №{order.id}</strong><span className="text-xs text-muted">{order.created_date}</span><span className="text-xs text-muted">{order.payment_status}</span></div><p className="mt-1 text-sm">{order.parts.length} поз. · закупка {money(order.total_price)}</p><div className="mt-2 grid gap-1.5">{order.parts.map((part) => { const disabled = !available.includes(part); const checked = selected.includes(part.article); return <label key={`${order.id}-${part.article}`} className={`flex items-center gap-2 text-xs ${disabled ? "text-muted line-through" : "text-white"}`}><input type="checkbox" checked={checked && !disabled} disabled={disabled || add.isPending || order.imported} onChange={() => setSelected((items) => checked ? items.filter((article) => article !== part.article) : [...items, part.article])} /><span>{part.brand} {part.name} × {part.quantity}</span><span className="text-muted">{money(part.purchase_price)}</span></label>; })}</div>{unavailable ? <p className="mt-1 text-xs text-muted">Недоступно: {unavailable}</p> : null}</div>
    <Button disabled={order.imported || add.isPending || add.isSuccess || !selected.length} onClick={() => add.mutate()}>{order.imported || add.isSuccess ? <><Check size={17} />Импортирован</> : <><Download size={17} />{selected.length === available.length ? "Добавить всё" : `Добавить выбранное (${selected.length})`}</>}</Button>
    {add.error && <p className="text-xs text-danger sm:col-span-2">Не удалось импортировать заказ. Возможно, он уже был добавлен.</p>}
  </div>;
}

function ProfitImport({ order, crmOrderId, markup }: { order: ProfitLigaOrder; crmOrderId: number; markup: number }) {
  const available = order.parts.filter((part) => !/отмен|возврат|отказ/i.test(part.status));
  const [selected, setSelected] = useState<string[]>(available.map((part) => part.article));
  const add = useMutation({
    mutationFn: () => api.importProfitLigaOrder(crmOrderId, order.id, markup, selected),
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["crm"] }), queryClient.invalidateQueries({ queryKey: ["profit-orders", crmOrderId] })]);
    },
  });
  const unavailable = order.parts.length - available.length;
  return <div className="grid gap-3 rounded-xl border border-line bg-panel-soft p-3 sm:grid-cols-[1fr_auto] sm:items-center">
    <div><div className="flex flex-wrap items-center gap-2"><strong>Profit Liga №{order.id}</strong><span className="text-xs text-muted">{order.created_date}</span><span className="text-xs text-muted">{order.payment_status}</span></div><p className="mt-1 text-sm">{order.parts.length} поз. · закупка {money(order.total_price)}</p><div className="mt-2 grid gap-1.5">{order.parts.map((part) => { const disabled = !available.includes(part); const checked = selected.includes(part.article); return <label key={`${order.id}-${part.article}`} className={`flex items-center gap-2 text-xs ${disabled ? "text-muted line-through" : "text-white"}`}><input type="checkbox" checked={checked && !disabled} disabled={disabled || add.isPending || order.imported} onChange={() => setSelected((items) => checked ? items.filter((article) => article !== part.article) : [...items, part.article])} /><span>{part.brand} {part.name} × {part.quantity}</span><span className="text-muted">{money(part.purchase_price)}</span></label>; })}</div>{unavailable ? <p className="mt-1 text-xs text-muted">Недоступно: {unavailable}</p> : null}</div>
    <Button disabled={order.imported || add.isPending || add.isSuccess || !selected.length} onClick={() => add.mutate()}>{order.imported || add.isSuccess ? <><Check size={17} />Импортирован</> : <><Download size={17} />{selected.length === available.length ? "Добавить всё" : `Добавить выбранное (${selected.length})`}</>}</Button>
    {add.error && <p className="text-xs text-danger sm:col-span-2">Не удалось импортировать заказ. Возможно, он уже был добавлен.</p>}
  </div>;
}

function Supplier({ name, connected }: { name: string; connected: boolean }) { return <span className={`rounded-full px-3 py-1 text-xs font-bold ${connected ? "bg-success/10 text-success" : "bg-panel-soft text-muted"}`}>{name} · {connected ? "подключён" : "нет ключа"}</span>; }

function Offer({ offer, orders, preferredOrderId }: { offer: SupplierOffer; orders: { id: number; label: string }[]; preferredOrderId: number }) {
  const [orderId, setOrderId] = useState(orders.some((order) => order.id === preferredOrderId) ? preferredOrderId : (orders[0]?.id ?? 0));
  const [quantity, setQuantity] = useState(1);
  const add = useMutation({ mutationFn: () => api.addPartToOrder(offer, orderId, quantity), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["crm"] }); } });
  return <Card className="grid gap-3 lg:grid-cols-[1fr_auto_auto_auto] lg:items-center">
    <div className="min-w-0"><div className="flex flex-wrap gap-2"><span className="rounded-lg bg-apex/10 px-2 py-1 text-xs font-black text-apex">{offer.supplier}</span><span className="text-sm font-bold text-muted">{offer.brand}</span></div><p className="mt-2 font-bold">{offer.name}</p><p className="mt-1 font-mono text-sm text-muted">{offer.article}</p><p className="mt-1 text-xs text-muted">В наличии: {offer.quantity} · Срок: {offer.delivery_days ? `${offer.delivery_days} дн.` : "сегодня"}{offer.warehouse ? ` · ${offer.warehouse}` : ""}</p></div>
    <div><p className="text-xs text-muted">Закупка</p><p className="font-bold">{money(offer.purchase_price)}</p></div><div><p className="text-xs text-muted">Клиенту · +{offer.markup_percent}%</p><p className="text-xl font-black text-apex">{money(offer.sale_price)}</p><p className="text-xs text-success">прибыль {money(offer.profit)}</p></div>
    <div className="grid min-w-56 gap-2"><select className="rounded-xl border border-line bg-canvas px-3 py-2 text-sm" value={orderId} onChange={(event) => setOrderId(Number(event.target.value))}><option value={0}>Выберите заказ-наряд</option>{orders.map((order) => <option key={order.id} value={order.id}>{order.label}</option>)}</select><div className="flex gap-2"><input className="w-16 rounded-xl border border-line bg-canvas px-2 text-center" type="number" min="1" max={Math.max(1, offer.quantity)} value={quantity} onChange={(event) => setQuantity(Math.max(1, Number(event.target.value)))} /><Button className="flex-1" disabled={!orderId || add.isPending || add.isSuccess} onClick={() => add.mutate()}>{add.isSuccess ? <><Check size={17} />Добавлено</> : <><ShoppingCart size={17} />В заказ</>}</Button></div>{add.error && <p className="text-xs text-danger">Не удалось добавить позицию</p>}</div>
  </Card>;
}
