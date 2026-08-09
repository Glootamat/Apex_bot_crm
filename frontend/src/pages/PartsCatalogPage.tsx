import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, PackageSearch, Search, ShoppingCart, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Card, EmptyState, inputClass, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { queryClient } from "../lib/query";
import type { SupplierOffer } from "../lib/types";
import { useCrm } from "../features/crm/useCrm";

export function PartsCatalogPage() {
  const [params] = useSearchParams();
  const initialQuery = params.get("q")?.trim() ?? "";
  const preferredOrderId = Number(params.get("order_id") || 0);
  const crm = useCrm();
  const status = useQuery({ queryKey: ["parts-catalog-status"], queryFn: api.partsCatalogStatus });
  const [query, setQuery] = useState(initialQuery);
  const [submitted, setSubmitted] = useState(initialQuery.length >= 3 ? initialQuery : "");
  const [markup, setMarkup] = useState<number | null>(null);
  const effectiveMarkup = markup ?? status.data?.default_markup_percent ?? 40;
  const search = useQuery({ queryKey: ["parts-catalog", submitted, effectiveMarkup], queryFn: () => api.searchParts(submitted, effectiveMarkup), enabled: submitted.length >= 3, retry: false });
  const activeOrders = useMemo(() => crm.data?.orders.filter((order) => order.status === "in_progress") ?? [], [crm.data]);

  if (status.isPending || crm.isPending) return <Spinner label="Открываю каталог…" />;
  return <div className="grid gap-4">
    <header><p className="text-sm font-bold text-apex">Запчасти</p><h1 className="text-2xl font-black sm:text-3xl">Проценка по артикулу</h1><p className="mt-1 text-sm text-muted">Один артикул одновременно проверяется в Profit Liga и ROSSKO</p></header>
    <Card>
      <form className="grid gap-3 sm:grid-cols-[1fr_auto]" onSubmit={(event) => { event.preventDefault(); if (query.trim().length >= 3) setSubmitted(query.trim()); }}>
        <div className="relative"><Search className="absolute left-4 top-1/2 -translate-y-1/2 text-muted" size={19} /><input className={`${inputClass} pl-11`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Введите точный артикул, например 26300" autoFocus /></div>
        <Button type="submit" disabled={query.trim().length < 3 || search.isFetching}>{search.isFetching ? "Ищу…" : "Найти"}</Button>
      </form>
      <div className="mt-4 flex flex-wrap items-center gap-3"><SlidersHorizontal size={18} className="text-apex" /><label className="flex items-center gap-2 text-sm text-muted">Наценка <input className="w-24 rounded-lg border border-line bg-canvas px-3 py-2 text-white" type="number" min="0" max="300" value={effectiveMarkup} onChange={(event) => setMarkup(Number(event.target.value))} />%</label><span className="rounded-lg bg-panel-soft px-3 py-2 text-sm text-muted">Цена округляется вверх до 50 ₽</span><Supplier name="ROSSKO" connected={status.data?.suppliers.rossko ?? false} /><Supplier name="Profit Liga" connected={status.data?.suppliers.profit_liga ?? false} /></div>
    </Card>
    {!status.data?.suppliers.rossko && !status.data?.suppliers.profit_liga && <Card className="border-apex/30 bg-apex/5"><p className="font-bold">Поставщики ещё не подключены</p><p className="mt-1 text-sm text-muted">Добавьте ключи ROSSKO и Profit Liga в настройки сервера. После этого цены и остатки появятся здесь автоматически.</p></Card>}
    {search.error && <Card className="border-danger/30 text-danger">Не удалось получить предложения поставщиков. Проверьте подключение и настройки API.</Card>}
    {search.data && <><div className="flex items-center justify-between"><h2 className="font-black">Предложения <span className="text-apex">{search.data.offers.length}</span></h2><span className="text-sm text-muted">Сначала выгодные</span></div>{search.data.offers.length ? <div className="grid gap-3">{search.data.offers.map((offer) => <Offer key={`${offer.supplier}-${offer.offer_id}`} offer={offer} orders={activeOrders.map((order) => ({ id: order.id, label: `№${order.id} · ${order.brand} ${order.model}` }))} preferredOrderId={preferredOrderId} />)}</div> : <EmptyState>По артикулу «{search.data.query}» предложений не найдено. Проверьте написание артикула без пробелов и лишних символов.</EmptyState>}</>}
    {!submitted && <EmptyState><PackageSearch className="mx-auto mb-3 text-apex" size={34} />Введите точный артикул. CRM покажет цены и остатки Profit Liga и ROSSKO, после чего позицию можно добавить в выбранный заказ.</EmptyState>}
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
