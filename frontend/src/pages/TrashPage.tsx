import { RotateCcw, Trash2 } from "lucide-react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryClient } from "../lib/query";
import { Button, Card, EmptyState, Spinner } from "../components/ui";
import { formatDateTime } from "../lib/format";
import type { TrashItem } from "../lib/types";

const labels: Record<TrashItem["kind"], string> = {
  customer: "Клиент",
  car: "Автомобиль",
  appointment: "Запись",
  order: "Заказ-наряд",
};

export function TrashPage() {
  const trash = useQuery({ queryKey: ["trash"], queryFn: api.trash });
  const restore = useMutation({
    mutationFn: (item: TrashItem) => api.restoreTrashItem(item.kind, item.id),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["trash"] }),
        queryClient.invalidateQueries({ queryKey: ["crm"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ]);
    },
  });

  if (trash.isPending) return <Spinner label="Открываю корзину…" />;
  if (trash.isError || !trash.data) return <EmptyState>Не удалось загрузить корзину</EmptyState>;
  return <div className="grid gap-5">
    <header><p className="text-sm font-bold text-apex">ХРАНЕНИЕ {trash.data.retention_days} ДНЕЙ</p><h1 className="text-3xl font-black">Корзина</h1><p className="mt-1 text-muted">Удалённые данные можно восстановить. Через {trash.data.retention_days} дней они удаляются безвозвратно.</p></header>
    {restore.isError && <p className="rounded-xl bg-danger/10 p-3 text-danger">Не удалось восстановить запись. Возможно, связанное место в календаре уже занято.</p>}
    {trash.data.items.length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{trash.data.items.map((item) => <Card key={`${item.kind}-${item.id}`} className="flex flex-col gap-4"><div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-panel-soft text-apex"><Trash2 size={18} /></span><div className="min-w-0"><p className="text-xs font-bold uppercase text-apex">{labels[item.kind]}</p><h2 className="break-words font-black">{item.title}</h2>{item.subtitle && <p className="break-words text-sm text-muted">{item.subtitle}</p>}<p className="mt-1 text-xs text-muted">Удалено: {formatDateTime(item.archived_at)}</p></div></div><Button variant="secondary" className="mt-auto" disabled={restore.isPending} onClick={() => restore.mutate(item)}><RotateCcw size={17} />Восстановить</Button></Card>)}</div> : <EmptyState>Корзина пуста</EmptyState>}
  </div>;
}
