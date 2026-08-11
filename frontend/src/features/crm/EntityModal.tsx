import { Camera, ScanLine } from "lucide-react";
import { useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "../../lib/api";
import { refreshCrm } from "../../lib/query";
import type { Appointment, AppointmentInput, Car, CarInput, Customer, CustomerInput, Order, OrderInput } from "../../lib/types";
import { carName } from "../../lib/format";
import { Button, Field, inputClass, Modal } from "../../components/ui";

type Entity =
  | { kind: "customer"; value?: Customer }
  | { kind: "car"; value?: Car; customerId?: number }
  | { kind: "appointment"; value?: Appointment; carId?: number }
  | { kind: "order"; value?: Order; carId?: number };

export type EntityModalState = Entity | null;
type Props = { entity: Entity; customers: Customer[]; cars: Car[]; onClose: () => void; onSaved?: () => void };

const text = (data: FormData, key: string) => { const value = data.get(key); return typeof value === "string" ? value.trim() : ""; };
const optional = (data: FormData, key: string) => text(data, key) || null;
const number = (data: FormData, key: string) => { const value = text(data, key); return value ? Number(value) : null; };
const requiredNumber = (data: FormData, key: string) => Number(text(data, key));
const moneyInput = (value: number | undefined) => ({
  type: "number" as const, min: "0", inputMode: "numeric" as const,
  defaultValue: value ?? 0,
  onFocus: (event: React.FocusEvent<HTMLInputElement>) => {
    if (event.currentTarget.value === "0") event.currentTarget.select();
  },
  onInput: (event: React.FormEvent<HTMLInputElement>) => {
    event.currentTarget.value = event.currentTarget.value.replace(/^0+(?=\d)/, "");
  },
});

export function EntityModal({ entity, customers, cars, onClose, onSaved }: Props) {
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);

  const mutation = useMutation({
    mutationFn: async (data: FormData) => {
      if (entity.kind === "customer") {
        const payload: CustomerInput = { full_name: text(data, "full_name"), phone: optional(data, "phone") };
        return api.saveCustomer(payload, entity.value?.id);
      }
      if (entity.kind === "car") {
        const payload: CarInput = { customer_id: number(data, "customer_id"), brand: text(data, "brand"), model: text(data, "model"), year: number(data, "year"), plate_number: optional(data, "plate_number"), vin: optional(data, "vin"), mileage: number(data, "mileage") };
        return api.saveCar(payload, entity.value?.id);
      }
      if (entity.kind === "appointment") {
        const payload: AppointmentInput = { car_id: requiredNumber(data, "car_id"), description: text(data, "description"), starts_at: text(data, "starts_at"), agreed_amount: number(data, "agreed_amount"), is_flexible: data.get("is_flexible") === "on", parts_source: optional(data, "parts_source") };
        return api.saveAppointment(payload, entity.value?.id);
      }
      const payload: OrderInput = { car_id: requiredNumber(data, "car_id"), description: text(data, "description"), labor_revenue: number(data, "labor_revenue") ?? 0, parts_cost: number(data, "parts_cost") ?? 0, parts_revenue: number(data, "parts_revenue") ?? 0, parts_profit: number(data, "parts_profit") ?? 0, concern: optional(data, "concern"), agreed_amount: number(data, "agreed_amount"), recommendations: optional(data, "recommendations"), parts_source: optional(data, "parts_source") };
      return api.saveOrder(payload, entity.value?.id);
    },
    onSuccess: async () => { await refreshCrm(); onSaved?.(); onClose(); },
  });
  const applyVehicleRecognition = (result: Awaited<ReturnType<typeof api.recognizeVehicleImage>>) => {
    const form = formRef.current;
    if (!form) return;
    const set = (name: string, value: string | number | null) => {
      if (value == null || value === "") return;
      const input = form.elements.namedItem(name);
      if (input instanceof HTMLInputElement) input.value = String(value);
    };
    set("vin", result.vin); set("plate_number", result.plate_number);
    set("brand", result.brand); set("model", result.model); set("year", result.year);
  };
  const recognition = useMutation({
    mutationFn: ({ file, vin }: { file?: File; vin?: string }) => file ? api.recognizeVehicleImage(file) : api.recognizeVehicleVin(vin ?? ""),
    onSuccess: applyVehicleRecognition,
  });
  const recognizeTypedVin = () => {
    const input = formRef.current?.elements.namedItem("vin");
    if (input instanceof HTMLInputElement) recognition.mutate({ vin: input.value });
  };

  const edit = Boolean(entity.value);
  const title = `${edit ? "Изменить" : "Создать"} ${{ customer: "клиента", car: "автомобиль", appointment: "запись", order: "заказ-наряд" }[entity.kind]}`;
  const submit = (event: React.FormEvent<HTMLFormElement>) => { event.preventDefault(); mutation.mutate(new FormData(event.currentTarget)); };
  const error = mutation.error instanceof ApiError ? mutation.error.message : mutation.error ? "Не удалось сохранить" : "";

  return <Modal title={title} onClose={onClose}>
    <form ref={formRef} className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
      {entity.kind === "customer" && <>
        <Field label="Имя клиента" full><input className={inputClass} name="full_name" defaultValue={entity.value?.full_name ?? ""} placeholder="Если неизвестно — оставьте пустым" /></Field>
        <Field label="Телефон" full><input className={inputClass} name="phone" type="tel" inputMode="tel" defaultValue={entity.value?.phone ?? ""} placeholder="+7 900 000-00-00" /></Field>
      </>}
      {entity.kind === "car" && <>
        <label className="inline-flex min-h-12 cursor-pointer items-center justify-center gap-2 rounded-xl border border-apex/40 bg-apex/10 px-4 py-2 text-sm font-bold text-apex transition hover:bg-apex/15 sm:col-span-2"><Camera size={18} />{recognition.isPending ? "Распознаю…" : "Сканировать VIN / ПТС / СТС"}<input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" disabled={recognition.isPending} onChange={(event) => { const file = event.target.files?.[0]; if (file) recognition.mutate({ file }); event.currentTarget.value = ""; }} /></label>
        {recognition.data && <p className="rounded-xl bg-success/10 p-3 text-sm text-success sm:col-span-2">Распознано: {[recognition.data.brand, recognition.data.model, recognition.data.year, recognition.data.vin].filter(Boolean).join(" · ") || "проверьте изображение"}. Поля заполнены автоматически — проверьте перед сохранением.</p>}
        {recognition.error && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger sm:col-span-2">Не удалось распознать VIN или документ. Сделайте фото без бликов либо введите VIN вручную.</p>}
        <Field label="Клиент" full><select className={inputClass} name="customer_id" defaultValue={entity.value?.customer_id ?? entity.customerId ?? ""}><option value="">Без клиента</option>{customers.map((item) => <option key={item.id} value={item.id}>{item.full_name}{item.phone ? ` · ${item.phone}` : ""}</option>)}</select></Field>
        <Field label="Марка"><input className={inputClass} name="brand" required defaultValue={entity.value?.brand ?? ""} /></Field>
        <Field label="Модель"><input className={inputClass} name="model" required defaultValue={entity.value?.model ?? ""} /></Field>
        <Field label="Год"><input className={inputClass} name="year" type="number" min="1900" max="2100" defaultValue={entity.value?.year ?? ""} /></Field>
        <Field label="Госномер"><input className={inputClass} name="plate_number" defaultValue={entity.value?.plate_number ?? ""} /></Field>
        <Field label="VIN" full><div className="grid gap-2 sm:grid-cols-[1fr_auto]"><input className={inputClass} name="vin" maxLength={17} defaultValue={entity.value?.vin ?? ""} autoCapitalize="characters" placeholder="17 символов" /><Button type="button" variant="secondary" onClick={recognizeTypedVin} disabled={recognition.isPending}><ScanLine size={18} />Определить авто</Button></div></Field>
        <Field label="Пробег"><input className={inputClass} name="mileage" type="number" min="0" defaultValue={entity.value?.mileage ?? ""} /></Field>
      </>}
      {entity.kind === "appointment" && <>
        <Field label="Автомобиль" full><select className={inputClass} name="car_id" required defaultValue={entity.value?.car_id ?? entity.carId ?? ""}><option value="">Выберите автомобиль</option>{cars.map((item) => <option key={item.id} value={item.id}>{carName(item)}</option>)}</select></Field>
        <Field label="Дата и время" full><input className={inputClass} name="starts_at" type="datetime-local" required defaultValue={entity.value?.starts_at.slice(0, 16) ?? ""} /></Field>
        <Field label="Причина обращения" full><textarea className={`${inputClass} min-h-24 resize-y`} name="description" required defaultValue={entity.value?.description ?? ""} /></Field>
        <Field label="Согласованная сумма"><input className={inputClass} name="agreed_amount" type="number" min="0" defaultValue={entity.value?.agreed_amount ?? ""} /></Field>
        <Field label="Запчасти"><select className={inputClass} name="parts_source" defaultValue={entity.value?.parts_source ?? ""}><option value="">Не указано</option><option value="workshop">Наши</option><option value="customer">Клиента</option></select></Field>
        <label className="flex min-h-12 items-center gap-3 text-sm text-muted sm:col-span-2"><input className="size-5 accent-apex" name="is_flexible" type="checkbox" defaultChecked={entity.value?.is_flexible ?? false} />Время можно изменить</label>
      </>}
      {entity.kind === "order" && <>
        <Field label="Автомобиль" full><select className={inputClass} name="car_id" required defaultValue={entity.value?.car_id ?? entity.carId ?? ""}><option value="">Выберите автомобиль</option>{cars.map((item) => <option key={item.id} value={item.id}>{carName(item)}</option>)}</select></Field>
        <Field label="Работы" full><textarea className={`${inputClass} min-h-24 resize-y`} name="description" required defaultValue={entity.value?.description ?? ""} /></Field>
        <Field label="Оплата за работу"><input className={inputClass} name="labor_revenue" {...moneyInput(entity.value?.labor_revenue)} /></Field>
        <Field label="Закупка запчастей"><input className={inputClass} name="parts_cost" {...moneyInput(entity.value?.parts_cost)} /></Field>
        <Field label="Продажа запчастей"><input className={inputClass} name="parts_revenue" {...moneyInput(entity.value?.parts_revenue)} /></Field>
        <Field label="Доп. прибыль по запчастям"><input className={inputClass} name="parts_profit" {...moneyInput(entity.value?.parts_profit)} /></Field>
        <Field label="Жалоба клиента" full><textarea className={inputClass} name="concern" defaultValue={entity.value?.concern ?? ""} /></Field>
        <Field label="Согласованная сумма"><input className={inputClass} name="agreed_amount" type="number" min="0" defaultValue={entity.value?.agreed_amount ?? ""} /></Field>
        <Field label="Запчасти"><select className={inputClass} name="parts_source" defaultValue={entity.value?.parts_source ?? ""}><option value="">Не указано</option><option value="workshop">Наши</option><option value="customer">Клиента</option></select></Field>
        <Field label="Рекомендации" full><textarea className={inputClass} name="recommendations" defaultValue={entity.value?.recommendations ?? ""} /></Field>
      </>}
      {error && <p className="rounded-xl bg-danger/10 p-3 text-sm text-danger sm:col-span-2" role="alert">{error}</p>}
      <div className="mt-2 flex flex-col-reverse gap-2 sm:col-span-2 sm:flex-row sm:justify-end"><Button type="button" variant="secondary" onClick={onClose}>Отмена</Button><Button type="submit" disabled={mutation.isPending}>{mutation.isPending ? "Сохраняю…" : "Сохранить"}</Button></div>
    </form>
  </Modal>;
}
