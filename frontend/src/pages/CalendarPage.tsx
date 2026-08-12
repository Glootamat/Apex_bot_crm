import { CalendarPlus, Check, Clock3, Pencil, Trash2, UserX } from "lucide-react";
import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useOutletContext } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { customerName, formatDateTime, statusLabel } from "../lib/format";
import { refreshCrm } from "../lib/query";
import { useCrm } from "../features/crm/useCrm";
import type { Appointment } from "../lib/types";

export function CalendarPage() {
  const { openEntity, openDetail } = useOutletContext<AppOutlet>();
  const crm = useCrm();
  const action = useMutation({ mutationFn: ({ id, value }: { id: number; value: "arrived" | "no_show" }) => api.appointmentAction(id, value), onSuccess: refreshCrm });
  const remove = useMutation({ mutationFn: api.deleteAppointment, onSuccess: refreshCrm });
  if (crm.isPending) return <Spinner />;
  const items = crm.data?.appointments ?? [];
  const [month, setMonth] = useState(() => new Date());
  const calendarDays = useMemo(() => monthDays(month, items), [month, items]);
  const deleteAppointment = (id: number) => {
    if (window.confirm("Удалить предварительную запись? Она будет храниться в корзине 30 дней.")) remove.mutate(id);
  };

  return <div className="grid gap-5">
    <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-sm font-bold text-apex">РАСПИСАНИЕ</p><h1 className="text-3xl font-black">Календарь записей</h1><p className="mt-1 text-muted">{items.length} ближайших визитов</p></div><Button onClick={() => openEntity({ kind: "appointment" })}><CalendarPlus size={18} />Новая запись</Button></header>
    <Card className="overflow-hidden p-0"><div className="flex items-center justify-between border-b border-line p-3"><Button variant="ghost" onClick={() => setMonth((value) => new Date(value.getFullYear(), value.getMonth() - 1, 1))}>←</Button><strong className="capitalize">{month.toLocaleDateString("ru-RU", { month: "long", year: "numeric" })}</strong><Button variant="ghost" onClick={() => setMonth((value) => new Date(value.getFullYear(), value.getMonth() + 1, 1))}>→</Button></div><div className="grid grid-cols-7 gap-px bg-line text-center text-[10px] text-muted">{"Пн Вт Ср Чт Пт Сб Вс".split(" ").map((day) => <span key={day} className="bg-panel py-2 font-bold">{day}</span>)}{calendarDays.map((day, index) => <button key={index} type="button" onClick={() => day.items[0] && openDetail({ kind: "appointment", value: day.items[0] })} className={`min-h-14 bg-canvas p-1 text-left transition hover:bg-panel-soft ${day.current ? "" : "text-muted/40"}`}><span className="block text-right text-xs">{day.date.getDate()}</span>{day.items.slice(0, 2).map((item) => <span key={item.id} className="mt-0.5 block truncate rounded bg-info/15 px-1 text-[9px] font-bold text-info">{item.starts_at.slice(11, 16)} {item.brand}</span>)}{day.items.length > 2 && <span className="block px-1 text-[9px] text-apex">ещё {day.items.length - 2}</span>}</button>)}</div></Card>
    {action.error && <p className="rounded-xl bg-danger/10 p-3 text-danger">Не удалось изменить статус записи</p>}
    {remove.error && <p className="rounded-xl bg-danger/10 p-3 text-danger">Не удалось удалить предварительную запись</p>}
    <div className="grid min-w-0 gap-3">{items.length ? items.map((item) => <Card key={item.id} className="grid min-w-0 cursor-pointer gap-4 p-4 transition hover:border-apex/50 lg:grid-cols-[170px_1fr_auto] lg:items-center" onClick={() => openDetail({ kind: "appointment", value: item })}>
      <div><p className="flex min-w-0 items-center gap-2 break-words font-bold text-apex"><Clock3 className="shrink-0" size={17} />{formatDateTime(item.starts_at)}</p><span className="mt-2 inline-flex rounded-full bg-info/10 px-2 py-1 text-xs font-bold text-info">{statusLabel(item.status)}</span></div>
      <div className="min-w-0"><h2 className="break-words text-lg font-black">{item.brand} {item.model}{item.plate_number ? ` · ${item.plate_number}` : ""}</h2><p className="mt-1 break-words text-muted">{item.description}</p><p className="mt-2 break-words text-sm">{customerName(item.customer_name)}{item.customer_phone ? ` · ${item.customer_phone}` : ""}</p><p className="mt-2 text-xs font-semibold text-apex">Нажмите для подробностей</p></div>
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap lg:justify-end"><Button variant="secondary" onClick={(event) => { event.stopPropagation(); openEntity({ kind: "appointment", value: item }); }}><Pencil size={16} />Изменить</Button>{item.status === "scheduled" && <><Button onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "arrived" }); }} disabled={action.isPending || remove.isPending}><Check size={16} />Приехал</Button><Button variant="danger" onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "no_show" }); }} disabled={action.isPending || remove.isPending}><UserX size={16} />Не приехал</Button>{!item.service_order_id && <Button variant="danger" onClick={(event) => { event.stopPropagation(); deleteAppointment(item.id); }} disabled={remove.isPending || action.isPending}><Trash2 size={16} />Удалить</Button>}</>}</div>
    </Card>) : <EmptyState>Записей пока нет. Добавьте первую запись.</EmptyState>}</div>
  </div>;
}

function monthDays(month: Date, items: Appointment[]) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1); const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));
  return Array.from({ length: 42 }, (_, index) => { const date = new Date(start); date.setDate(start.getDate() + index); const key = date.toLocaleDateString("sv-SE"); return { date, current: date.getMonth() === month.getMonth(), items: items.filter((item) => item.starts_at.slice(0, 10) === key) }; });
}
