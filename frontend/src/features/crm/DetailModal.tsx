import {
  CalendarDays,
  Camera,
  CarFront,
  CheckCircle2,
  ClipboardCheck,
  ClipboardList,
  FileDown,
  FileImage,
  Pencil,
  PackageSearch,
  Save,
  Share2,
  RotateCcw,
  Trash2,
  UserRound,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import type {
  Appointment,
  Car,
  CrmData,
  Customer,
  Order,
  OrderAttachment,
} from "../../lib/types";
import {
  customerName,
  formatDateTime,
  money,
  parseCrmDate,
  statusLabel,
} from "../../lib/format";
import { api } from "../../lib/api";
import { refreshCrm } from "../../lib/query";
import { exportOrderImage, exportOrderPdf } from "../../lib/orderImage";
import { Button, Modal } from "../../components/ui";
import type { EntityModalState } from "./EntityModal";

type Detail =
  | { kind: "customer"; value: Customer }
  | { kind: "car"; value: Car }
  | { kind: "appointment"; value: Appointment }
  | { kind: "order"; value: Order };
export type DetailModalState = Detail | null;
type Props = {
  detail: Detail;
  data: CrmData;
  onClose: () => void;
  onEdit: (value: NonNullable<EntityModalState>) => void;
  onOpen: (value: Detail) => void;
};
const Row = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div className="min-w-0 rounded-xl bg-panel-soft p-3">
    <dt className="text-xs font-semibold uppercase tracking-wide text-muted">
      {label}
    </dt>
    <dd className="mt-1 whitespace-pre-line break-words font-semibold">{value || "Не указано"}</dd>
  </div>
);

export function DetailModal({ detail, data, onClose, onEdit, onOpen }: Props) {
  const navigate = useNavigate();
  const [attachments, setAttachments] = useState<OrderAttachment[]>(
    detail.kind === "order" ? (detail.value.attachments ?? []) : [],
  );
  const [orderExportOpen, setOrderExportOpen] = useState(false);
  const [photoSourceOpen, setPhotoSourceOpen] = useState(false);
  const [completionMileage, setCompletionMileage] = useState("");
  const cameraInput = useRef<HTMLInputElement>(null);
  const galleryInput = useRef<HTMLInputElement>(null);
  const remove = useMutation({
    mutationFn: () =>
      detail.kind === "customer"
        ? api.deleteCustomer(detail.value.id)
        : detail.kind === "car"
          ? api.deleteCar(detail.value.id)
          : detail.kind === "appointment"
            ? api.deleteAppointment(detail.value.id)
            : detail.kind === "order"
              ? api.deleteOrder(detail.value.id)
              : Promise.reject(new Error("Удаление недоступно")),
    onSuccess: async () => {
      await refreshCrm();
      onClose();
    },
  });
  const upload = useMutation({
    mutationFn: ({ file, type }: { file: File; type: "work" }) =>
      detail.kind === "order"
        ? api.uploadOrderPhoto(detail.value.id, file, type)
        : Promise.reject(new Error("Загрузка недоступна")),
    onSuccess: async (value) => {
      setAttachments((items) => [...items, value]);
      await refreshCrm();
    },
  });
  const orderStatus = useMutation({
    mutationFn: ({ action, mileageAtVisit }: { action: "ready" | "in_progress"; mileageAtVisit?: number }) =>
      detail.kind === "order"
        ? api.orderStatus(detail.value.id, action, mileageAtVisit)
        : Promise.reject(new Error("Изменение статуса недоступно")),
    onSuccess: async () => {
      await refreshCrm();
      onClose();
    },
  });
  const go = (path: string) => {
    void navigate(path);
    onClose();
  };
  const confirmRemove = (label: string) => {
    if (
      window.confirm(`Удалить ${label}? Связанные данные будут скрыты из CRM.`)
    )
      remove.mutate();
  };
  const selectPhoto = (file?: File) => { if (file) upload.mutate({ file, type: "work" }); setPhotoSourceOpen(false); };

  if (detail.kind === "customer") {
    const cars = data.cars.filter((x) => x.customer_id === detail.value.id);
    const carIds = new Set(cars.map((x) => x.id));
    const orders = data.orders.filter((x) => carIds.has(x.car_id));
    const visits = data.appointment_history.filter((x) => carIds.has(x.car_id));
    const contacts = recentContacts(visits, orders);
    return (
      <Modal title={customerName(detail.value.full_name)} onClose={onClose}>
        <div className="grid gap-4">
          <DetailHero icon={<UserRound size={24} />} eyebrow="Клиент" title={customerName(detail.value.full_name)} subtitle={detail.value.phone || "Телефон не указан"} tone="info" />
          <section className="grid grid-cols-3 gap-2"><QuickMetric label="Автомобили" value={cars.length} /><QuickMetric label="Заказы" value={orders.length} /><QuickMetric label="Прибыль" value={money(orders.reduce((sum, x) => sum + x.profit, 0))} tone="success" /></section>
          <dl className="grid gap-2 sm:grid-cols-2">
            <Row label="Телефон" value={detail.value.phone} />
            <button
              className="text-left"
              onClick={() => go(`/cars?customer_id=${detail.value.id}`)}
            >
              <Row label="Автомобилей" value={cars.length} />
            </button>
            <button
              className="text-left"
              onClick={() => go(`/orders?customer_id=${detail.value.id}`)}
            >
              <Row label="Заказ-нарядов" value={orders.length} />
            </button>
            <button
              className="text-left"
              onClick={() => go(`/finance?customer_id=${detail.value.id}`)}
            >
              <Row
                label="Общая прибыль"
                value={
                  <span className="text-success">
                    {money(orders.reduce((sum, x) => sum + x.profit, 0))}
                  </span>
                }
              />
            </button>
          </dl>
          <Related title="Автомобили" empty="Автомобили не добавлены">
            {cars.map((x) => (
              <Link
                key={x.id}
                onClick={() => onOpen({ kind: "car", value: x })}
                icon={<CarFront />}
              >
                {x.brand} {x.model}
                {x.plate_number ? ` · ${x.plate_number}` : ""}
              </Link>
            ))}
          </Related>
          <Related title="Последние обращения" empty="Обращений пока нет">
            {contacts.slice(0, 5).map((x) =>
              x.kind === "appointment" ? (
                <Link
                  key={`a-${x.value.id}`}
                  onClick={() =>
                    onOpen({ kind: "appointment", value: x.value })
                  }
                  icon={<CalendarDays />}
                >
                  {formatDateTime(x.date)} · {x.value.description}
                </Link>
              ) : (
                <Link
                  key={`o-${x.value.id}`}
                  onClick={() => onOpen({ kind: "order", value: x.value })}
                  icon={<ClipboardList />}
                >
                  {formatDateTime(x.date)} · {x.value.description}
                </Link>
              ),
            )}
          </Related>
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="danger"
              onClick={() => confirmRemove("клиента")}
              disabled={remove.isPending}
            >
              <Trash2 size={17} />
              Удалить
            </Button>
            <Button
              variant="secondary"
              onClick={() =>
                onEdit({ kind: "car", customerId: detail.value.id })
              }
            >
              <CarFront size={17} />
              Добавить авто
            </Button>
            <Button
              onClick={() => onEdit({ kind: "customer", value: detail.value })}
            >
              <Pencil size={17} />
              Изменить
            </Button>
          </div>
        </div>
      </Modal>
    );
  }
  if (detail.kind === "car") {
    const owner = data.customers.find((x) => x.id === detail.value.customer_id);
    const orders = data.orders.filter((x) => x.car_id === detail.value.id);
    const visits = data.appointment_history.filter(
      (x) => x.car_id === detail.value.id,
    );
    const contacts = recentContacts(visits, orders);
    return (
      <Modal
        title={`${detail.value.brand} ${detail.value.model}`}
        onClose={onClose}
      >
        <div className="grid gap-4">
          <DetailHero icon={<CarFront size={24} />} eyebrow="Автомобиль" title={`${detail.value.brand} ${detail.value.model}`} subtitle={detail.value.plate_number || "Госномер не указан"} tone="apex" />
          <section className="grid grid-cols-3 gap-2"><QuickMetric label="Год" value={detail.value.year || "—"} /><QuickMetric label="Пробег" value={detail.value.mileage ? `${detail.value.mileage.toLocaleString("ru-RU")} км` : "—"} /><QuickMetric label="Заказы" value={orders.length} tone="success" /></section>
          <dl className="grid gap-2 sm:grid-cols-2">
            <Row label="Госномер" value={detail.value.plate_number} />
            <Row label="Год" value={detail.value.year} />
            <Row
              label="Пробег"
              value={
                detail.value.mileage
                  ? `${detail.value.mileage.toLocaleString("ru-RU")} км`
                  : null
              }
            />
            <Row
              label="VIN"
              value={
                <span className="break-all font-mono text-sm">
                  {detail.value.vin || "Не указано"}
                </span>
              }
            />
          </dl>
          {owner && (
            <Related title="Владелец">
              <Link
                onClick={() => onOpen({ kind: "customer", value: owner })}
                icon={<UserRound />}
              >
                {customerName(owner.full_name)}
                {owner.phone ? ` · ${owner.phone}` : ""}
              </Link>
            </Related>
          )}
          <Related title="История заказов" empty="Заказов пока нет">
            {orders.map((x) => (
              <Link
                key={x.id}
                onClick={() => onOpen({ kind: "order", value: x })}
                icon={<ClipboardList />}
              >
                #{x.id} · {x.description} · {money(x.profit)}
              </Link>
            ))}
          </Related>
          <Related title="Последние обращения" empty="Обращений пока нет">
            {contacts.slice(0, 5).map((x) =>
              x.kind === "appointment" ? (
                <Link
                  key={`a-${x.value.id}`}
                  onClick={() =>
                    onOpen({ kind: "appointment", value: x.value })
                  }
                  icon={<CalendarDays />}
                >
                  {formatDateTime(x.date)} · {x.value.description}
                </Link>
              ) : (
                <Link
                  key={`o-${x.value.id}`}
                  onClick={() => onOpen({ kind: "order", value: x.value })}
                  icon={<ClipboardList />}
                >
                  {formatDateTime(x.date)} · {x.value.description}
                </Link>
              ),
            )}
          </Related>
          <div className="grid gap-2 sm:grid-cols-2">
            <Button
              className="sm:col-span-2"
              variant="secondary"
              onClick={() => go(`/cars/${detail.value.id}/history`)}
            >
              <ClipboardList size={17} />
              История автомобиля
            </Button>
            <Button
              variant="secondary"
              onClick={() => go(`/orders?car_id=${detail.value.id}`)}
            >
              <ClipboardList size={17} />
              Все заказ-наряды
            </Button>
            <Button
              variant="secondary"
              onClick={() =>
                onEdit({ kind: "appointment", carId: detail.value.id })
              }
            >
              Новая запись
            </Button>
            <Button
              variant="secondary"
              onClick={() => onEdit({ kind: "order", carId: detail.value.id })}
            >
              Новый заказ
            </Button>
            <Button
              onClick={() => onEdit({ kind: "car", value: detail.value })}
            >
              <Pencil size={17} />
              Изменить
            </Button>
            <Button
              className="sm:col-span-2"
              variant="danger"
              onClick={() => confirmRemove("автомобиль")}
              disabled={remove.isPending}
            >
              <Trash2 size={17} />
              Удалить автомобиль
            </Button>
          </div>
        </div>
      </Modal>
    );
  }
  if (detail.kind === "appointment")
    return (
      <Modal title={`Запись #${detail.value.id}`} onClose={onClose}>
        <div className="grid gap-4">
          <DetailHero icon={<CalendarDays size={24} />} eyebrow="Предварительная запись" title={`${detail.value.brand} ${detail.value.model}`} subtitle={formatDateTime(detail.value.starts_at)} tone="info" badge={statusLabel(detail.value.status)} />
          <section className="grid grid-cols-2 gap-2"><QuickMetric label="Клиент" value={customerName(detail.value.customer_name)} /><QuickMetric label="Согласовано" value={detail.value.agreed_amount == null ? "Не указано" : money(detail.value.agreed_amount)} tone="apex" /></section>
          <dl className="grid gap-2 sm:grid-cols-2">
            <Row
              label="Дата и время"
              value={formatDateTime(detail.value.starts_at)}
            />
            <Row label="Статус" value={statusLabel(detail.value.status)} />
            <Row
              label="Автомобиль"
              value={`${detail.value.brand} ${detail.value.model}${detail.value.plate_number ? ` · ${detail.value.plate_number}` : ""}`}
            />
            <Row
              label="Клиент"
              value={customerName(detail.value.customer_name)}
            />
            <Row label="Телефон" value={detail.value.customer_phone} />
            <Row
              label="Согласовано"
              value={
                detail.value.agreed_amount == null
                  ? null
                  : money(detail.value.agreed_amount)
              }
            />
          </dl>
          <Row label="Причина обращения" value={detail.value.description} />
          {remove.error && (
            <p className="text-sm text-danger">Не удалось удалить запись</p>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            {detail.value.status === "scheduled" &&
              !detail.value.service_order_id && (
                <Button
                  variant="danger"
                  onClick={() => {
                    if (
                      window.confirm(
                        "Удалить предварительную запись? Отменить действие будет нельзя.",
                      )
                    )
                      remove.mutate();
                  }}
                  disabled={remove.isPending}
                >
                  <Trash2 size={17} />
                  Удалить запись
                </Button>
              )}
            <Button
              onClick={() =>
                onEdit({ kind: "appointment", value: detail.value })
              }
            >
              <Pencil size={17} />
              Изменить запись
            </Button>
          </div>
        </div>
      </Modal>
    );
  const o = detail.value;
  const currentCarMileage = data.cars.find((item) => item.id === o.car_id)?.mileage ?? o.mileage;
  const finishOrder = () => {
    const value = completionMileage.trim();
    if (value && (!/^\d+$/.test(value) || Number(value) > 10_000_000)) {
      window.alert("Укажите пробег целым числом в километрах.");
      return;
    }
    const mileageAtVisit = value ? Number(value) : currentCarMileage ?? undefined;
    if (mileageAtVisit == null) {
      window.alert("Перед завершением укажите пробег автомобиля на момент визита.");
      return;
    }
    orderStatus.mutate({ action: "ready", mileageAtVisit });
  };
  const markup = o.parts_revenue === 0
    ? o.parts_profit
    : o.parts_revenue - o.parts_cost + o.parts_profit;
  const works = attachments.filter((x) => x.photo_type === "work" && x.url);
  const diagnosticAction = (
    <Button
      variant="secondary"
      onClick={() =>
        go(`/diagnostics/start?car_id=${o.car_id}&order_id=${o.id}`)
      }
    >
      <ClipboardCheck size={17} />
      Диагностика
    </Button>
  );
  return (
    <Modal title={`Заказ-наряд #${o.id}`} onClose={onClose}>
      <div className="grid gap-4">
        <DetailHero icon={<CarFront size={24} />} eyebrow={`Заказ-наряд #${o.id}`} title={`${o.brand} ${o.model}`} subtitle={o.plate_number || customerName(o.customer_name)} tone="apex" badge={statusLabel(o.status)} />
        <section className="grid grid-cols-2 gap-2 sm:grid-cols-4"><QuickMetric label="Создан" value={formatDateTime(o.created_at)} /><QuickMetric label="Работы" value={money(o.labor_revenue)} tone="apex" /><QuickMetric label="Запчасти" value={money(o.parts_revenue)} /><QuickMetric label="Прибыль" value={money(o.profit)} tone="success" /></section>
        <dl className="grid gap-2 sm:grid-cols-2">
          <Row
            label="Автомобиль"
            value={`${o.brand} ${o.model}${o.plate_number ? ` · ${o.plate_number}` : ""}`}
          />
          <Row label="Клиент" value={customerName(o.customer_name)} />
          <Row label="Статус" value={statusLabel(o.status)} />
          <Row label="Создан" value={formatDateTime(o.created_at)} />
          <Row label="Работы" value={money(o.labor_revenue)} />
          <Row label="Закупка запчастей" value={money(o.parts_cost)} />
          <Row label="Продажа запчастей" value={money(o.parts_revenue)} />
          <Row label="Наценка запчастей" value={money(markup)} />
          <Row
            label="Общая выручка"
            value={money(o.labor_revenue + o.parts_revenue)}
          />
          <Row
            label="Итоговая прибыль"
            value={<span className="text-success">{money(o.profit)}</span>}
          />
        </dl>
        {!o.concern?.startsWith("По результатам диагностики №") && <Row label="Жалоба клиента" value={o.concern} />}
        <Row label="Выполненные работы" value={o.description} />
        <Row label="Пробег на момент визита" value={o.mileage_at_visit ? `${o.mileage_at_visit.toLocaleString("ru-RU")} км` : null} />
        <Row label="Рекомендации" value={o.recommendations} />
        <Gallery title="Фото работ" items={works} />
        {upload.error && (
          <p className="text-sm text-danger">
            Не удалось загрузить фото. Используйте JPG, PNG или WebP до 10 МБ.
          </p>
        )}
        {remove.error && (
          <p className="text-sm text-danger">Не удалось удалить заказ-наряд</p>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button
            variant="primary"
            className="sm:col-span-2"
            onClick={() => go(`/parts-catalog?order_id=${o.id}`)}
          >
            <PackageSearch size={17} />
            Подобрать запчасти и загрузить заказ поставщика
          </Button>
          <Button variant="secondary" onClick={() => setPhotoSourceOpen(true)} disabled={upload.isPending}><Camera size={17} />{upload.isPending ? "Загрузка…" : "Добавить фото работ"}</Button>
          <Button variant="secondary" onClick={() => setOrderExportOpen((current) => !current)}>
            <Save size={17} />
            Сохранить
          </Button>
          <Button variant="secondary" onClick={() => void exportOrderImage(o, true)}>
            <Share2 size={17} />
            Поделиться
          </Button>
          {orderExportOpen && <div className="grid gap-2 rounded-xl border border-apex/30 bg-panel-soft p-3 sm:col-span-2 sm:grid-cols-2">
            <Button variant="secondary" onClick={() => { setOrderExportOpen(false); void exportOrderPdf(o); }}><FileDown size={17} />Сохранить PDF</Button>
            <Button variant="secondary" onClick={() => { setOrderExportOpen(false); void exportOrderImage(o, false); }}><FileImage size={17} />Сохранить картинкой</Button>
          </div>}
          {diagnosticAction}
          {!["ready", "completed"].includes(o.status) && !o.mileage_at_visit && <label className="grid gap-1 rounded-xl border border-apex/30 bg-apex/5 p-3 text-sm sm:col-span-2"><span className="font-bold text-apex">Пробег на момент визита</span><span className="text-xs text-muted">Сохранится в истории автомобиля и обновит текущий пробег, если значение больше.</span><input className="mt-1 rounded-lg border border-line bg-canvas px-3 py-2 font-bold text-white outline-none transition focus:border-apex" type="number" min="0" inputMode="numeric" value={completionMileage} onChange={(event) => setCompletionMileage(event.target.value)} placeholder={currentCarMileage != null ? `${currentCarMileage} км` : "Например, 24000"} /></label>}
          {!["ready", "completed"].includes(o.status) ? (
            <Button className="sm:col-span-2" onClick={finishOrder} disabled={orderStatus.isPending}>
              <CheckCircle2 size={17} />
              {orderStatus.isPending ? "Сохраняю…" : "Завершить заказ"}
            </Button>
          ) : (
            <Button className="sm:col-span-2" variant="secondary" onClick={() => orderStatus.mutate({ action: "in_progress" })} disabled={orderStatus.isPending}>
              <RotateCcw size={17} />
              {orderStatus.isPending ? "Возвращаю…" : "Вернуть в работу"}
            </Button>
          )}
          {orderStatus.error && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger sm:col-span-2">Не удалось изменить статус заказ-наряда</p>}
          <Button className="sm:col-span-2" onClick={() => onEdit({ kind: "order", value: o })}>
            <Pencil size={17} />
            Изменить заказ-наряд
          </Button>
          <Button
            className="sm:col-span-2"
            variant="danger"
            onClick={() => {
              if (
                window.confirm(
                  "Удалить заказ-наряд? Он будет исключён из списков и финансов. Действие фиксируется в архиве.",
                )
              )
                remove.mutate();
            }}
            disabled={remove.isPending}
          >
            <Trash2 size={17} />
            Удалить заказ-наряд
          </Button>
        </div>
        {photoSourceOpen && <Modal title="Добавить фото работ" onClose={() => setPhotoSourceOpen(false)}><div className="grid grid-cols-2 gap-2"><Button className="min-h-24 flex-col" variant="secondary" onClick={() => cameraInput.current?.click()}><Camera size={25} />Камера</Button><Button className="min-h-24 flex-col" variant="secondary" onClick={() => galleryInput.current?.click()}><FileImage size={25} />Галерея</Button></div></Modal>}
        <input ref={cameraInput} className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(event) => { selectPhoto(event.target.files?.[0]); event.currentTarget.value = ""; }} />
        <input ref={galleryInput} className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => { selectPhoto(event.target.files?.[0]); event.currentTarget.value = ""; }} />
      </div>
    </Modal>
  );
}
function ProtectedOrderPhoto({ item, title }: { item: OrderAttachment; title: string }) {
  const photo = useQuery({ queryKey: ["order-photo", item.id, item.url], queryFn: async () => URL.createObjectURL(await api.orderPhoto(item.url!)), staleTime: Infinity });
  useEffect(() => () => { if (photo.data) URL.revokeObjectURL(photo.data); }, [photo.data]);
  if (photo.isPending) return <div className="aspect-square animate-pulse rounded-xl bg-panel-soft" />;
  if (photo.isError || !photo.data) return <div className="grid aspect-square place-items-center rounded-xl bg-danger/10 p-2 text-center text-xs text-danger">Фото недоступно</div>;
  return <a href={photo.data} target="_blank" rel="noreferrer"><img className="aspect-square w-full rounded-xl object-cover" src={photo.data} alt={item.caption || title} loading="lazy" /></a>;
}
function Gallery({
  title,
  items,
}: {
  title: string;
  items: OrderAttachment[];
}) {
  if (!items.length) return null;
  return (
    <section>
      <h3 className="mb-2 font-black">{title}</h3>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {items.map((item) => <ProtectedOrderPhoto key={item.id} item={item} title={title} />)}
      </div>
    </section>
  );
}
function DetailHero({ icon, eyebrow, title, subtitle, tone, badge }: { icon: React.ReactNode; eyebrow: string; title: string; subtitle: string; tone: "apex" | "info" | "success"; badge?: string }) {
  const tones = { apex: "bg-apex/12 text-apex", info: "bg-info/12 text-info", success: "bg-success/12 text-success" };
  return <section className="overflow-hidden rounded-2xl border border-line bg-gradient-to-br from-panel to-panel-soft p-4 shadow-card"><div className="flex items-start gap-3"><span className={`grid size-12 shrink-0 place-items-center rounded-2xl ${tones[tone]}`}>{icon}</span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="text-xs font-bold uppercase tracking-wide text-muted">{eyebrow}</p>{badge && <span className="rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-bold text-success">{badge}</span>}</div><h2 className="mt-1 break-words text-xl font-black">{title}</h2><p className="mt-1 break-all text-sm text-muted">{subtitle}</p></div></div></section>;
}
function QuickMetric({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "apex" | "success" }) {
  return <div className="min-w-0 rounded-xl border border-line/70 bg-canvas/60 p-3"><p className="truncate text-[10px] font-bold uppercase tracking-wide text-muted">{label}</p><strong className={`mt-1 block break-words text-sm sm:text-base ${tone === "success" ? "text-success" : tone === "apex" ? "text-apex" : "text-white"}`}>{value}</strong></div>;
}
function recentContacts(visits: Appointment[], orders: Order[]) {
  const linked = new Set(
    visits.map((visit) => visit.service_order_id).filter(Boolean),
  );
  return [
    ...visits.map((value) => ({
      kind: "appointment" as const,
      value,
      date: value.starts_at,
    })),
    ...orders
      .filter((value) => !linked.has(value.id))
      .map((value) => ({
        kind: "order" as const,
        value,
        date: value.completed_at || value.created_at,
      })),
  ].sort(
    (a, b) => parseCrmDate(b.date).valueOf() - parseCrmDate(a.date).valueOf(),
  );
}
function Related({
  title,
  children,
  empty,
}: React.PropsWithChildren<{ title: string; empty?: string }>) {
  const count = Array.isArray(children) ? children.length : children ? 1 : 0;
  return (
    <section>
      <h3 className="mb-2 font-black">{title}</h3>
      <div className="grid gap-2">
        {count ? (
          children
        ) : (
          <p className="rounded-xl bg-panel-soft p-3 text-sm text-muted">
            {empty}
          </p>
        )}
      </div>
    </section>
  );
}
function Link({
  children,
  icon,
  onClick,
}: React.PropsWithChildren<{ icon: React.ReactNode; onClick: () => void }>) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-w-0 items-center gap-3 rounded-xl bg-panel-soft p-3 text-left text-sm transition hover:bg-line"
    >
      <span className="shrink-0 text-apex">{icon}</span>
      <span className="min-w-0 break-words">{children}</span>
    </button>
  );
}
