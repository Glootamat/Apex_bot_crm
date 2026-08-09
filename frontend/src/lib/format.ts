export const money = (value: number | null | undefined) =>
  new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 }).format(value ?? 0);

export const customerName = (value: string | null | undefined) => {
  const name = value?.trim() ?? "";
  return !name || /^клиент\s*\+?[\d\s()-]+$/iu.test(name) ? "Имя не указано" : name;
};

export const formatDateTime = (value: string) => {
  const date = parseCrmDate(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit", month: "long", hour: "2-digit", minute: "2-digit",
    timeZone: "Europe/Moscow",
  }).format(date);
};

export const parseCrmDate = (value: string) => {
  // SQLite CURRENT_TIMESTAMP is UTC. Appointment values without an offset
  // represent workshop wall time in Moscow, regardless of the browser timezone.
  const normalized = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value)
    ? `${value.replace(" ", "T")}Z`
    : /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/.test(value)
      ? `${value}+03:00`
      : value;
  return new Date(normalized);
};

export const carName = (car: { brand: string; model: string; plate_number?: string | null }) =>
  `${car.brand} ${car.model}${car.plate_number ? ` · ${car.plate_number}` : ""}`;

export const statusLabel = (status: string) => ({
  in_progress: "В работе", planned: "Запланирован", ready: "Выполнен", completed: "Выполнен",
  no_show: "Не приехал", scheduled: "Записан",
})[status] ?? status;
