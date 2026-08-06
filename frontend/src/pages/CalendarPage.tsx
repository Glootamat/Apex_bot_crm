import { CalendarPlus, Check, Clock3, Pencil, UserX } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useOutletContext } from "react-router-dom";
import type { AppOutlet } from "../app/AppShell";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { customerName, formatDateTime, statusLabel } from "../lib/format";
import { refreshCrm } from "../lib/query";
import { useCrm } from "../features/crm/useCrm";

export function CalendarPage() {
  const { openEntity, openDetail } = useOutletContext<AppOutlet>();
  const crm = useCrm();
  const action = useMutation({ mutationFn: ({ id, value }: { id: number; value: "arrived" | "no_show" }) => api.appointmentAction(id, value), onSuccess: refreshCrm });
  if (crm.isPending) return <Spinner />;
  const items = crm.data?.appointments ?? [];
  return <div className="grid gap-5"><header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-sm font-bold text-apex">РАСПИСАНИЕ</p><h1 className="text-3xl font-black">Календарь записей</h1><p className="mt-1 text-muted">{items.length} ближайших визитов</p></div><Button onClick={() => openEntity({ kind: "appointment" })}><CalendarPlus size={18} />Новая запись</Button></header>
    {action.error && <p className="rounded-xl bg-danger/10 p-3 text-danger">Не удалось изменить статус записи</p>}
    <div className="grid min-w-0 gap-3">{items.length ? items.map((item) => <Card key={item.id} className="grid cursor-pointer min-w-0 gap-4 p-4 transition hover:border-apex/50 lg:grid-cols-[170px_1fr_auto] lg:items-center" onClick={() => openDetail({ kind: "appointment", value: item })}><div><p className="flex min-w-0 items-center gap-2 break-words font-bold text-apex"><Clock3 className="shrink-0" size={17} />{formatDateTime(item.starts_at)}</p><span className="mt-2 inline-flex rounded-full bg-info/10 px-2 py-1 text-xs font-bold text-info">{statusLabel(item.status)}</span></div><div className="min-w-0"><h2 className="break-words text-lg font-black">{item.brand} {item.model}{item.plate_number ? ` · ${item.plate_number}` : ""}</h2><p className="mt-1 break-words text-muted">{item.description}</p><p className="mt-2 break-words text-sm">{customerName(item.customer_name)}{item.customer_phone ? ` · ${item.customer_phone}` : ""}</p><p className="mt-2 text-xs font-semibold text-apex">Нажмите для подробностей</p></div><div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap lg:justify-end"><Button variant="secondary" onClick={(event) => { event.stopPropagation(); openEntity({ kind: "appointment", value: item }); }}><Pencil size={16} />Изменить</Button>{item.status === "scheduled" && <><Button onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "arrived" }); }} disabled={action.isPending}><Check size={16} />Приехал</Button><Button variant="danger" onClick={(event) => { event.stopPropagation(); action.mutate({ id: item.id, value: "no_show" }); }} disabled={action.isPending}><UserX size={16} />Не приехал</Button></>}</div></Card>) : <EmptyState>Записей пока нет. Добавьте первую запись.</EmptyState>}</div>
  </div>;
}
