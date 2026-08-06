import { CarFront, Pencil, Plus, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { Button, Card, EmptyState, inputClass, Spinner } from "../components/ui";
import { customerName } from "../lib/format";
import { useCrm } from "../features/crm/useCrm";

export function CustomersPage() {
  const { openEntity } = useOutletContext<AppOutlet>(); const crm = useCrm(); const [filter, setFilter] = useState("");
  const items = useMemo(() => { const q = filter.trim().toLocaleLowerCase("ru"); return (crm.data?.customers ?? []).filter((item) => !q || `${item.full_name} ${item.phone ?? ""}`.toLocaleLowerCase("ru").includes(q)); }, [crm.data?.customers, filter]);
  if (crm.isPending) return <Spinner />;
  return <div className="grid gap-5"><header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-sm font-bold text-apex">БАЗА CRM</p><h1 className="text-3xl font-black">Клиенты</h1><p className="mt-1 text-muted">{crm.data?.customers.length ?? 0} карточек</p></div><Button onClick={() => openEntity({ kind: "customer" })}><UserPlus size={18} />Новый клиент</Button></header><input className={inputClass} value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Фильтр по имени или телефону" aria-label="Фильтр клиентов" />
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{items.length ? items.map((item) => { const cars = crm.data?.cars.filter((car) => car.customer_id === item.id) ?? []; return <Card key={item.id} className="flex flex-col"><div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-black">{customerName(item.full_name)}</h2><p className="mt-1 text-sm text-muted">{item.phone || "Телефон не указан"}</p></div><Button variant="ghost" className="size-11 p-0" onClick={() => openEntity({ kind: "customer", value: item })} aria-label={`Изменить клиента ${customerName(item.full_name)}`}><Pencil size={18} /></Button></div><div className="mt-5 grid gap-2">{cars.map((car) => <div key={car.id} className="flex items-center gap-2 rounded-xl bg-panel-soft p-3 text-sm"><CarFront className="text-apex" size={18} /><span className="truncate">{car.brand} {car.model}{car.plate_number ? ` · ${car.plate_number}` : ""}</span></div>)}</div><Button variant="secondary" className="mt-auto pt-3" onClick={() => openEntity({ kind: "car", customerId: item.id })}><Plus size={16} />Добавить автомобиль</Button></Card>; }) : <div className="md:col-span-2 xl:col-span-3"><EmptyState>Клиенты не найдены</EmptyState></div>}</div>
  </div>;
}
