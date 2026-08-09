import type { Order } from "./types";
import { customerName, money } from "./format";

const loadImage = (src: string) => new Promise<HTMLImageElement>((resolve, reject) => {
  const image = new Image(); image.onload = () => resolve(image); image.onerror = reject; image.src = src;
});

export function containSize(sourceWidth: number, sourceHeight: number, maxWidth: number, maxHeight: number) {
  const scale = Math.min(maxWidth / sourceWidth, maxHeight / sourceHeight);
  return { width: Math.round(sourceWidth * scale), height: Math.round(sourceHeight * scale) };
}

export function orderCustomerLabel(order: Pick<Order, "customer_name" | "brand" | "model">) {
  const name = customerName(order.customer_name);
  const car = `${order.brand} ${order.model}`.trim();
  return name.localeCompare(car, "ru", { sensitivity: "base" }) === 0 ? "Не указан" : name;
}

function wrap(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, width: number, line = 42) {
  const words = text.split(/\s+/); let row = ""; let top = y;
  for (const word of words) { const next = `${row} ${word}`.trim(); if (ctx.measureText(next).width > width && row) { ctx.fillText(row, x, top); row = word; top += line; } else row = next; }
  if (row) ctx.fillText(row, x, top); return top + line;
}

export async function shareOrderImage(order: Order) {
  const canvas = document.createElement("canvas"); canvas.width = 1080; canvas.height = 1350;
  const ctx = canvas.getContext("2d"); if (!ctx) throw new Error("Canvas недоступен");
  ctx.fillStyle = "#090d12"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#ffd600"; ctx.fillRect(0, 0, 26, canvas.height);
  try {
    const logo = await loadImage("/assets/brand/apex-logo.png");
    const size = containSize(logo.naturalWidth || logo.width, logo.naturalHeight || logo.height, 150, 125);
    ctx.drawImage(logo, 70, 38, size.width, size.height);
  } catch { ctx.fillStyle = "#ffd600"; ctx.font = "900 44px sans-serif"; ctx.fillText("APEX AUTO", 70, 115); }
  ctx.textAlign = "right"; ctx.fillStyle = "#96a1ad"; ctx.font = "600 27px sans-serif"; ctx.fillText(`ЗАКАЗ-НАРЯД №${order.id}`, 1010, 95); ctx.textAlign = "left";
  ctx.fillStyle = "#ffffff"; ctx.font = "900 54px sans-serif"; ctx.fillText(`${order.brand} ${order.model}`, 70, 235);
  ctx.fillStyle = "#96a1ad"; ctx.font = "500 28px sans-serif"; ctx.fillText([order.plate_number, order.vin].filter(Boolean).join(" · ") || "Данные автомобиля не указаны", 70, 282);
  const row = (label: string, value: string, y: number) => { ctx.fillStyle = "#96a1ad"; ctx.font = "600 25px sans-serif"; ctx.fillText(label.toUpperCase(), 70, y); ctx.fillStyle = "#fff"; ctx.font = "700 31px sans-serif"; return wrap(ctx, value || "Не указано", 70, y + 43, 940, 40) + 22; };
  let y = row("Клиент", orderCustomerLabel(order), 355); y = row("Выполненные работы", order.description, y); if (order.recommendations) row("Рекомендации", order.recommendations, y);
  const total = order.labor_revenue + order.parts_revenue;
  ctx.fillStyle = "#18222d"; ctx.beginPath(); ctx.roundRect(70, 1120, 940, 150, 28); ctx.fill();
  ctx.fillStyle = "#96a1ad"; ctx.font = "600 27px sans-serif"; ctx.fillText("ИТОГО К ОПЛАТЕ", 105, 1182);
  ctx.fillStyle = "#ffd600"; ctx.font = "900 52px sans-serif"; ctx.textAlign = "right"; ctx.fillText(money(total), 970, 1200); ctx.textAlign = "left";
  ctx.fillStyle = "#96a1ad"; ctx.font = "500 22px sans-serif"; ctx.fillText("Спасибо, что выбрали Apex Auto", 70, 1310);
  const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error("Не удалось создать изображение")), "image/png"));
  const file = new File([blob], `zakaz-naryad-${order.id}.png`, { type: "image/png" });
  if (navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] }))) { await navigator.share({ title: `Заказ-наряд №${order.id}`, files: [file] }); return; }
  const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = file.name; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
