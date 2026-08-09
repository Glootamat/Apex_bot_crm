import {
  CalendarDays,
  Camera,
  CarFront,
  ClipboardCheck,
  ClipboardList,
  Pencil,
  Receipt,
  Share2,
  Trash2,
  UserRound,
} from "lucide-react";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import type {
  Appointment,
  Car,
  CrmData,
  Customer,
  Order,
  OrderAttachment,
  ReceiptUploadResult,
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
import { shareOrderImage } from "../../lib/orderImage";
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
    <dd className="mt-1 break-words font-semibold">{value || "Не указано"}</dd>
  </div>
);

export function DetailModal({ detail, data, onClose, onEdit, onOpen }: Props) {
  const navigate = useNavigate();
  const [attachments, setAttachments] = useState<OrderAttachment[]>(
    detail.kind === "order" ? (detail.value.attachments ?? []) : [],
  );
  const [receiptResult, setReceiptResult] =
    useState<ReceiptUploadResult | null>(null);
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
    mutationFn: ({ file, type }: { file: File; type: "work" | "receipt" }) =>
      detail.kind === "order"
        ? api.uploadOrderPhoto(detail.value.id, file, type)
        : Promise.reject(new Error("Загрузка недоступна")),
    onSuccess: async (value) => {
      setAttachments((items) => [...items, value]);
      setReceiptResult(value.photo_type === "receipt" ? value : null);
      await refreshCrm();
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
  const uploadInput = (
    type: "work" | "receipt",
    icon: React.ReactNode,
    label: string,
  ) => (
    <label className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-xl bg-panel-soft px-4 py-2 text-sm font-bold hover:bg-line">
      {icon}
      {upload.isPending
        ? type === "receipt"
          ? "Распознаю чек…"
          : "Загрузка…"
        : label}
      <input
        className="sr-only"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        disabled={upload.isPending}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) upload.mutate({ file, type });
          event.currentTarget.value = "";
        }}
      />
    </label>
  );

  if (detail.kind === "customer") {
    const cars = data.cars.filter((x) => x.customer_id === detail.value.id);
    const carIds = new Set(cars.map((x) => x.id));
    const orders = data.orders.filter((x) => carIds.has(x.car_id));
    const visits = data.appointment_history.filter((x) => carIds.has(x.car_id));
    const contacts = recentContacts(visits, orders);
    return (
      <Modal title={customerName(detail.value.full_name)} onClose={onClose}>
        <div className="grid gap-4">
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
  const markup = o.parts_revenue - o.parts_cost + o.parts_profit;
  const works = attachments.filter((x) => x.photo_type === "work" && x.url);
  const receipts = attachments.filter(
    (x) => x.photo_type === "receipt" && x.url,
  );
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
        <Row label="Жалоба клиента" value={o.concern} />
        <Row label="Выполненные работы" value={o.description} />
        <Row label="Рекомендации" value={o.recommendations} />
        <Gallery title="Фото работ" items={works} />
        <Gallery title="Фото чеков" items={receipts} />
        {receiptResult?.recognized && (
          <p className="rounded-xl bg-success/10 p-3 text-sm text-success">
            Распознано позиций: {receiptResult.items_count}. Закупка:{" "}
            {money(receiptResult.purchase_cost)}. Наценка{" "}
            {receiptResult.markup_percent}%:{" "}
            {money(receiptResult.markup_profit)}. Цена клиенту:{" "}
            {money(receiptResult.selling_price)}.
          </p>
        )}
        {receiptResult?.recognition_error && (
          <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">
            Фото сохранено, но чек не расшифрован:{" "}
            {receiptResult.recognition_error}
          </p>
        )}
        {upload.error && (
          <p className="text-sm text-danger">
            Не удалось загрузить фото. Используйте JPG, PNG или WebP до 10 МБ.
          </p>
        )}
        {remove.error && (
          <p className="text-sm text-danger">Не удалось удалить заказ-наряд</p>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          {uploadInput("work", <Camera size={17} />, "Добавить фото работ")}
          {uploadInput(
            "receipt",
            <Receipt size={17} />,
            upload.isPending ? "Распознаю чек…" : "Добавить чек и наценить",
          )}
          <Button variant="secondary" onClick={() => void shareOrderImage(o)}>
            <Share2 size={17} />
            Отправить картинкой
          </Button>
          {diagnosticAction}
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
      </div>
    </Modal>
  );
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
        {items.map((item) => (
          <a key={item.id} href={item.url!} target="_blank" rel="noreferrer">
            <img
              className="aspect-square w-full rounded-xl object-cover"
              src={item.url!}
              alt={item.caption || title}
              loading="lazy"
            />
          </a>
        ))}
      </div>
    </section>
  );
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
