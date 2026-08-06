import { CalendarDays, CarFront, ClipboardList, Search, UserRound } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useOutletContext } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { api } from "../lib/api";
import { carName, customerName, formatDateTime } from "../lib/format";
import { Button, Card, EmptyState, inputClass } from "../components/ui";

export function SearchPage() {
  const { openDetail } = useOutletContext<AppOutlet>();
  const [input, setInput] = useState(""); const [query, setQuery] = useState("");
  const result = useQuery({ queryKey: ["search", query], queryFn: () => api.search(query), enabled: query.length >= 2 });
  const total = result.data ? result.data.customers.length + result.data.cars.length + result.data.orders.length + result.data.appointments.length : 0;
  return <div className="grid gap-6"><header><p className="text-sm font-bold text-apex">БЫСТРЫЙ ПОИСК</p><h1 className="text-3xl font-black">Поиск по всей CRM</h1><p className="mt-1 text-muted">Имя, фамилия, телефон, машина, VIN, госномер, причина обращения</p></header><form className="flex flex-col gap-2 sm:flex-row" onSubmit={(event) => { event.preventDefault(); const value = input.trim(); if (value.length >= 2) setQuery(value); }}><input className={inputClass} value={input} onChange={(event) => setInput(event.target.value)} autoFocus placeholder="Например: Ниссан Тиана, Александр или А123ВС" aria-label="Поисковый запрос" /><Button type="submit" disabled={input.trim().length < 2 || result.isFetching}><Search size={18} />{result.isFetching ? "Ищу…" : "Найти"}</Button></form>
    {result.error && <p className="rounded-xl bg-danger/10 p-4 text-danger" role="alert">Не удалось выполнить поиск</p>}
    {query && result.data && <><p className="text-sm text-muted">Найдено: {total}</p>{total ? <div className="grid min-w-0 gap-5">{result.data.customers.length > 0 && <ResultGroup title="Клиенты" icon={<UserRound />} items={result.data.customers.map((item) => ({ id: `customer-${item.id}`, title: customerName(item.full_name), text: item.phone || "Телефон не указан", onClick: () => openDetail({ kind: "customer", value: item }) }))} />}{result.data.cars.length > 0 && <ResultGroup title="Автомобили" icon={<CarFront />} items={result.data.cars.map((item) => ({ id: `car-${item.id}`, title: carName(item), text: `${item.vin || "VIN не указан"}${item.mileage ? ` · ${item.mileage.toLocaleString("ru-RU")} км` : ""}`, onClick: () => openDetail({ kind: "car", value: item }) }))} />}{result.data.orders.length > 0 && <ResultGroup title="Заказ-наряды" icon={<ClipboardList />} items={result.data.orders.map((item) => ({ id: `order-${item.id}`, title: `#${item.id} · ${item.brand} ${item.model}`, text: item.description, onClick: () => openDetail({ kind: "order", value: item }) }))} />}{result.data.appointments.length > 0 && <ResultGroup title="Записи" icon={<CalendarDays />} items={result.data.appointments.map((item) => ({ id: `appointment-${item.id}`, title: `${item.brand} ${item.model} · ${formatDateTime(item.starts_at)}`, text: item.description, onClick: () => openDetail({ kind: "appointment", value: item }) }))} />}</div> : <EmptyState>По запросу «{query}» ничего не найдено. Попробуйте телефон без пробелов, часть VIN или другую транслитерацию модели.</EmptyState>}</>}
  </div>;
}

function ResultGroup({ title, icon, items }: { title: string; icon: React.ReactNode; items: { id: string; title: string; text: string; onClick: () => void }[] }) {
  return <section className="min-w-0"><h2 className="mb-3 flex items-center gap-2 text-lg font-black text-apex">{icon}{title}</h2><div className="grid min-w-0 gap-2 md:grid-cols-2">{items.map((item) => <Card key={item.id} className="cursor-pointer p-4 transition hover:border-apex/50" onClick={item.onClick}><h3 className="break-words font-bold">{item.title}</h3><p className="mt-1 break-words text-sm text-muted">{item.text}</p><p className="mt-2 text-xs font-semibold text-apex">Открыть подробную карточку</p></Card>)}</div></section>;
}
