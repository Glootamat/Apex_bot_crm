export const money = (value: number | null | undefined) =>
  new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 }).format(value ?? 0);

export const customerName = (value: string | null | undefined) => {
  const name = value?.trim() ?? "";
  return !name || /^клиент\s*\+?\d+$/iu.test(name) ? "Имя не указано" : name;
};

export const formatDateTime = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit", month: "long", hour: "2-digit", minute: "2-digit",
  }).format(date);
};

export const carName = (car: { brand: string; model: string; plate_number?: string | null }) =>
  `${car.brand} ${car.model}${car.plate_number ? ` · ${car.plate_number}` : ""}`;

export const statusLabel = (status: string) => ({
  in_progress: "В работе", planned: "Запланирован", ready: "Выполнен", completed: "Выполнен",
  no_show: "Не приехал", scheduled: "Записан",
})[status] ?? status;
