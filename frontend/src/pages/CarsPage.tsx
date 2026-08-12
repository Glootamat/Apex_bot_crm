import { CalendarPlus, ClipboardCheck, ClipboardPlus, Pencil, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useOutletContext, useSearchParams } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { Button, Card, EmptyState, inputClass, Spinner } from "../components/ui";
import { customerName } from "../lib/format";
import { useCrm } from "../features/crm/useCrm";
import { VehicleBadge } from "../components/VehicleBadge";

export function CarsPage() {
  const { openEntity, openDetail } = useOutletContext<AppOutlet>();
  const navigate = useNavigate();
  const crm = useCrm();
  const [filter, setFilter] = useState("");
  const [params] = useSearchParams();
  const customerId = Number(params.get("customer_id")) || null;
  const items = useMemo(() => {
    const query = filter.trim().toLocaleLowerCase("ru");
    return (crm.data?.cars ?? []).filter((item) => (!customerId || item.customer_id === customerId) && (!query || `${item.brand} ${item.model} ${item.plate_number ?? ""} ${item.vin ?? ""}`.toLocaleLowerCase("ru").includes(query)));
  }, [crm.data?.cars, customerId, filter]);
  if (crm.isPending) return <Spinner />;

  return <div className="grid min-w-0 gap-5">
    <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-sm font-bold text-apex">АВТОПАРК</p><h1 className="text-3xl font-black">Автомобили</h1><p className="mt-1 text-muted">{crm.data?.cars.length ?? 0} автомобилей</p></div><Button onClick={() => openEntity({ kind: "car" })}><Plus size={18} />Добавить автомобиль</Button></header>
    <input className={inputClass} value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Фильтр по марке, модели, номеру или VIN" aria-label="Фильтр автомобилей" />
    <div className="grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-3">{items.length ? items.map((item) => {
      const owner = crm.data?.customers.find((customer) => customer.id === item.customer_id);
      return <Card key={item.id} className="group cursor-pointer overflow-hidden p-0 transition hover:-translate-y-0.5 hover:border-apex/50" onClick={() => openDetail({ kind: "car", value: item })}>
        <div className="flex min-w-0 items-start gap-3 border-b border-line bg-gradient-to-br from-panel-soft to-panel p-4"><VehicleBadge brand={item.brand} model={item.model} /><div className="min-w-0 flex-1"><p className="text-[10px] font-bold uppercase tracking-wide text-muted">Автомобиль</p><h2 className="break-words text-xl font-black">{item.brand} {item.model}</h2><p className="break-words text-sm font-semibold text-muted">{item.plate_number || "Госномер не указан"}</p></div><Button variant="ghost" className="size-10 shrink-0 p-0" onClick={(event) => { event.stopPropagation(); openEntity({ kind: "car", value: item }); }} aria-label={`Изменить ${item.brand} ${item.model}`}><Pencil size={18} /></Button></div>
        <dl className="grid min-w-0 grid-cols-2 gap-px bg-line text-sm"><div className="min-w-0 bg-panel p-3"><dt className="text-[10px] uppercase text-muted">Владелец</dt><dd className="mt-1 break-words font-semibold">{customerName(owner?.full_name)}</dd></div><div className="bg-panel p-3"><dt className="text-[10px] uppercase text-muted">Пробег</dt><dd className="mt-1 font-semibold">{item.mileage ? `${item.mileage.toLocaleString("ru-RU")} км` : "Не указан"}</dd></div><div className="bg-panel p-3"><dt className="text-[10px] uppercase text-muted">Год</dt><dd className="mt-1 font-semibold">{item.year || "Не указан"}</dd></div><div className="min-w-0 bg-panel p-3"><dt className="text-[10px] uppercase text-muted">VIN</dt><dd className="mt-1 truncate font-mono text-xs">{item.vin || "Не указан"}</dd></div></dl>
        <div className="grid gap-2 p-3 sm:grid-cols-3"><Button variant="secondary" onClick={(event) => { event.stopPropagation(); openEntity({ kind: "appointment", carId: item.id }); }}><CalendarPlus size={16} />Запись</Button><Button variant="secondary" onClick={(event) => { event.stopPropagation(); openEntity({ kind: "order", carId: item.id }); }}><ClipboardPlus size={16} />Заказ</Button><Button onClick={(event) => { event.stopPropagation(); void navigate(`/diagnostics/start?car_id=${item.id}`); }}><ClipboardCheck size={16} />Диагностика</Button></div>
        <button className="w-full border-t border-line p-3 text-center text-xs font-semibold text-apex" onClick={(event) => { event.stopPropagation(); void navigate(`/cars/${item.id}/history`); }}>Открыть историю автомобиля →</button>
      </Card>;
    }) : <div className="md:col-span-2 xl:col-span-3"><EmptyState>Автомобили не найдены</EmptyState></div>}</div>
  </div>;
}
