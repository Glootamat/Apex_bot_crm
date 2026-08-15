import type { DiagnosticPart, Order } from "./types";
import { customerName, money } from "./format";
import { drawApexReportBrand, drawApexThanksFooter } from "./brandCanvas";

export function containSize(sourceWidth: number, sourceHeight: number, maxWidth: number, maxHeight: number) {
  const scale = Math.min(maxWidth / sourceWidth, maxHeight / sourceHeight);
  return { width: Math.round(sourceWidth * scale), height: Math.round(sourceHeight * scale) };
}

export function orderCustomerLabel(order: Pick<Order, "customer_name" | "brand" | "model">) {
  const name = customerName(order.customer_name);
  const car = `${order.brand} ${order.model}`.trim();
  return name.localeCompare(car, "ru", { sensitivity: "base" }) === 0 ? "Не указан" : name;
}

function wrappedLines(ctx: CanvasRenderingContext2D, text: string, width: number) {
  const lines: string[] = [];
  let row = "";
  for (const word of text.trim().split(/\s+/)) {
    const next = `${row} ${word}`.trim();
    if (row && ctx.measureText(next).width > width) { lines.push(row); row = word; } else row = next;
  }
  if (row) lines.push(row);
  return lines;
}

function orderList(value: string, diagnostic = false) {
  const source = value.trim();
  const rawLines = source.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const header = diagnostic && /^По результатам диагностики №\d+:?$/i.test(rawLines[0] ?? "")
    ? rawLines.shift()
    : undefined;
  const raw = rawLines.join("\n") || source;
  const entries = raw
    .split(/(?:\r?\n|\s*•\s*|\s*;\s*)+/)
    .flatMap((item) => diagnostic ? [item] : item.split(/\s+(?=(?:замена|ремонт|установка|диагностика|регулировка|обслуживание|снятие|покраска)\b)/iu))
    .map((item) => item.replace(/^[-–—•]\s*/, "").trim())
    .filter(Boolean);
  return { header, entries: entries.length ? entries : [source] };
}

function drawLegacyPartIcon(ctx: CanvasRenderingContext2D, name: string, x: number, y: number) {
  const value = name.toLocaleLowerCase("ru-RU");
  ctx.save();
  ctx.strokeStyle = "#9aa6b2";
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const circle = (cx: number, cy: number, radius: number) => { ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2); ctx.stroke(); };
  if (/втул|сайлент|подшип|фильтр/.test(value)) {
    ctx.beginPath(); ctx.ellipse(x, y - 8, 13, 6, 0, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x - 13, y - 8); ctx.lineTo(x - 13, y + 9); ctx.ellipse(x, y + 9, 13, 6, 0, 0, Math.PI); ctx.lineTo(x + 13, y - 8); ctx.stroke();
    circle(x, y - 8, 4);
  } else if (/стойк|тяга|наконеч|рычаг|амортиз/.test(value)) {
    circle(x - 10, y + 10, 5); circle(x + 10, y - 10, 5);
    ctx.beginPath(); ctx.moveTo(x - 6, y + 6); ctx.lineTo(x + 6, y - 6); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x - 3, y + 8); ctx.lineTo(x + 8, y - 3); ctx.stroke();
  } else if (/колод/.test(value)) {
    ctx.beginPath(); ctx.roundRect(x - 14, y - 10, 28, 20, 5); ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y + 8, 9, Math.PI, Math.PI * 2); ctx.stroke();
  } else if (/диск|ступиц/.test(value)) {
    circle(x, y, 14); circle(x, y, 6); circle(x - 7, y - 7, 1); circle(x + 7, y - 7, 1); circle(x, y + 9, 1);
  } else if (/аккум/.test(value)) {
    ctx.beginPath(); ctx.roundRect(x - 15, y - 10, 30, 22, 3); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x - 9, y - 13); ctx.lineTo(x - 4, y - 13); ctx.moveTo(x + 5, y - 13); ctx.lineTo(x + 10, y - 13); ctx.moveTo(x - 9, y); ctx.lineTo(x - 3, y); ctx.moveTo(x + 4, y); ctx.lineTo(x + 10, y); ctx.moveTo(x + 7, y - 3); ctx.lineTo(x + 7, y + 3); ctx.stroke();
  } else if (/масл|жидк|антифриз/.test(value)) {
    ctx.beginPath(); ctx.moveTo(x, y - 15); ctx.bezierCurveTo(x - 15, y + 1, x - 11, y + 14, x, y + 15); ctx.bezierCurveTo(x + 11, y + 14, x + 15, y + 1, x, y - 15); ctx.stroke();
  } else if (/ламп|свеч/.test(value)) {
    circle(x, y - 5, 10); ctx.beginPath(); ctx.moveTo(x - 6, y + 4); ctx.lineTo(x - 4, y + 13); ctx.lineTo(x + 4, y + 13); ctx.lineTo(x + 6, y + 4); ctx.moveTo(x - 4, y + 17); ctx.lineTo(x + 4, y + 17); ctx.stroke();
  } else if (/ремень|цеп/.test(value)) {
    ctx.beginPath(); ctx.roundRect(x - 14, y - 11, 28, 22, 10); ctx.stroke();
    ctx.beginPath(); ctx.roundRect(x - 8, y - 5, 16, 10, 5); ctx.stroke();
  } else {
    ctx.beginPath(); ctx.moveTo(x, y - 15); ctx.lineTo(x + 13, y - 7); ctx.lineTo(x + 13, y + 8); ctx.lineTo(x, y + 15); ctx.lineTo(x - 13, y + 8); ctx.lineTo(x - 13, y - 7); ctx.closePath(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x - 13, y - 7); ctx.lineTo(x, y); ctx.lineTo(x + 13, y - 7); ctx.moveTo(x, y); ctx.lineTo(x, y + 15); ctx.stroke();
  }
  ctx.restore();
}

function partCategory(name: string) {
  const value = name.toLocaleLowerCase("ru-RU");
  if (/втул|сайлент|подшип|ступиц/.test(value)) return 0;
  if (/стабилиз|стойк|тяга|наконеч/.test(value)) return 1;
  if (/рычаг|шаров|амортиз|пружин/.test(value)) return 2;
  if (/колод|тормоз|диск/.test(value)) return 3;
  if (/фильтр|масл|жидк|антифриз/.test(value)) return 4;
  if (/аккум|ламп|свеч/.test(value)) return 5;
  return 6;
}

const partCategoryLabels = ["САЙЛЕНТБЛОКИ И ВТУЛКИ", "РУЛЕВОЕ И СТАБИЛИЗАТОР", "ПОДВЕСКА", "ТОРМОЗНАЯ СИСТЕМА", "ФИЛЬТРЫ И ЖИДКОСТИ", "ЭЛЕКТРИКА", "ПРОЧИЕ ЗАПЧАСТИ"];

function groupedParts(parts: DiagnosticPart[]) {
  const grouped = new Map<string, DiagnosticPart>();
  for (const part of parts) {
    const key = [part.name.trim().toLocaleLowerCase("ru-RU"), part.article ?? "", part.unit_cost ?? "", part.markup_percent ?? ""].join("|");
    const current = grouped.get(key);
    if (current) {
      const quantity = Number(current.quantity || 1) + Number(part.quantity || 1);
      grouped.set(key, { ...current, quantity, total_cost: Number(current.total_cost || 0) + Number(part.total_cost || 0), sale_total: Number(current.sale_total || 0) + Number(part.sale_total || 0) });
    } else grouped.set(key, { ...part });
  }
  return [...grouped.values()].sort((a, b) => partCategory(a.name) - partCategory(b.name) || a.name.localeCompare(b.name, "ru", { sensitivity: "base" }) || Number(a.unit_cost || 0) - Number(b.unit_cost || 0));
}

function drawPartIcon(ctx: CanvasRenderingContext2D, name: string, x: number, y: number) {
  const value = name.toLocaleLowerCase("ru-RU");
  ctx.save();
  ctx.fillStyle = "#182431";
  ctx.beginPath(); ctx.roundRect(x - 22, y - 22, 44, 44, 12); ctx.fill();
  ctx.strokeStyle = "#ffd600"; ctx.lineWidth = 2.4; ctx.lineCap = "round"; ctx.lineJoin = "round";
  const circle = (cx: number, cy: number, radius: number) => { ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2); ctx.stroke(); };
  if (/втул|сайлент|подшип|ступиц/.test(value)) {
    circle(x, y, 13); circle(x, y, 6);
    ctx.beginPath(); ctx.arc(x, y, 9.5, -0.7, 0.7); ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y, 9.5, Math.PI - 0.7, Math.PI + 0.7); ctx.stroke();
  } else if (/стабилиз|стойк|тяга|наконеч/.test(value)) {
    circle(x - 10, y + 10, 5); circle(x + 10, y - 10, 5);
    ctx.beginPath(); ctx.moveTo(x - 6, y + 6); ctx.lineTo(x + 6, y - 6); ctx.stroke();
    ctx.fillStyle = "#ffd600"; circle(x - 10, y + 10, 1.5); circle(x + 10, y - 10, 1.5);
  } else if (/рычаг|шаров/.test(value)) {
    circle(x - 12, y + 9, 4); circle(x + 12, y + 9, 4); circle(x, y - 11, 4);
    ctx.beginPath(); ctx.moveTo(x - 8, y + 7); ctx.lineTo(x - 2, y - 8); ctx.moveTo(x + 8, y + 7); ctx.lineTo(x + 2, y - 8); ctx.stroke();
  } else if (/пружин|амортиз/.test(value)) {
    ctx.beginPath(); ctx.moveTo(x, y - 15); ctx.bezierCurveTo(x - 15, y - 10, x + 15, y - 5, x, y); ctx.bezierCurveTo(x - 15, y + 5, x + 15, y + 10, x, y + 15); ctx.stroke();
  } else if (/колод|тормоз|диск/.test(value)) {
    circle(x, y, 14); circle(x, y, 5); ctx.beginPath(); ctx.arc(x + 8, y, 11, -0.8, 0.8); ctx.stroke();
  } else if (/масл|жидк|антифриз/.test(value)) {
    ctx.beginPath(); ctx.moveTo(x, y - 15); ctx.bezierCurveTo(x - 15, y + 2, x - 10, y + 15, x, y + 15); ctx.bezierCurveTo(x + 10, y + 15, x + 15, y + 2, x, y - 15); ctx.stroke();
  } else drawLegacyPartIcon(ctx, name, x, y);
  ctx.restore();
}

async function renderOrderCanvas(order: Order) {
  const parts = groupedParts(order.parts ?? []);
  const partGroupsCount = new Set(parts.map((part) => partCategory(part.name))).size;
  const textBlocks = [order.concern, order.description, order.recommendations].filter(Boolean).join(" ");
  const estimatedLines = Math.max(3, Math.ceil(textBlocks.length / 30));
  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = Math.max(1180, 900 + estimatedLines * 36 + parts.length * 92 + partGroupsCount * 30);
  const ctx = canvas.getContext("2d"); if (!ctx) throw new Error("Canvas недоступен");
  ctx.fillStyle = "#090d12"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  await drawApexReportBrand(ctx, 68, 24, 430);
  ctx.textAlign = "right"; ctx.fillStyle = "#96a1ad"; ctx.font = "700 25px sans-serif"; ctx.fillText(`ЗАКАЗ-НАРЯД №${order.id}`, 1010, 96); ctx.textAlign = "left";

  let y = 190;
  const panel = (top: number, height: number) => {
    ctx.fillStyle = "#111a23"; ctx.beginPath(); ctx.roundRect(68, top, 942, height, 22); ctx.fill();
    ctx.strokeStyle = "#2a3846"; ctx.lineWidth = 2; ctx.stroke();
  };
  panel(y, 202);
  ctx.fillStyle = "#fff"; ctx.font = "900 48px sans-serif"; ctx.fillText(`${order.brand} ${order.model}`, 98, y + 62);
  ctx.fillStyle = "#96a1ad"; ctx.font = "500 23px sans-serif";
  const carLine = [order.plate_number, order.vin, order.year ? `${order.year} г.` : null].filter(Boolean).join(" · ");
  ctx.fillText(carLine || "Данные автомобиля не указаны", 98, y + 101);
  const mileage = order.mileage_at_visit ?? order.mileage;
  if (mileage) ctx.fillText(`Пробег: ${mileage.toLocaleString("ru-RU")} км`, 98, y + 132);
  const clientLabelY = y + (mileage ? 158 : 132);
  ctx.fillStyle = "#96a1ad"; ctx.font = "700 17px sans-serif"; ctx.fillText("КЛИЕНТ", 98, clientLabelY);
  ctx.fillStyle = "#fff"; ctx.font = "700 25px sans-serif";
  ctx.fillText([orderCustomerLabel(order), order.customer_phone].filter(Boolean).join(" · "), 98, clientLabelY + 26);
  y += 230;

  const section = (label: string, value: string, price?: number, diagnostic = false) => {
    const list = orderList(value, diagnostic);
    ctx.font = "600 24px sans-serif";
    const textWidth = price != null ? 630 : 760;
    const headerLines = list.header ? wrappedLines(ctx, list.header, 850) : [];
    const itemLines = list.entries.map((item) => wrappedLines(ctx, item, textWidth));
    const contentHeight = headerLines.length * 31 + (headerLines.length ? 12 : 0)
      + itemLines.reduce((sum, lines) => sum + lines.length * 31 + 10, 0);
    const height = Math.max(82, 28 + contentHeight);
    ctx.fillStyle = "#fff"; ctx.font = "900 23px sans-serif"; ctx.fillText(label.toUpperCase(), 68, y + 22);
    panel(y + 42, height);
    ctx.fillStyle = "#fff"; ctx.font = "600 24px sans-serif";
    let contentY = y + 76;
    for (const line of headerLines) { ctx.fillText(line, 98, contentY); contentY += 31; }
    if (headerLines.length) contentY += 8;
    for (const lines of itemLines) {
      ctx.fillStyle = "#ffd600"; ctx.beginPath(); ctx.arc(106, contentY - 8, 4, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#fff";
      for (const line of lines) { ctx.fillText(line, 122, contentY); contentY += 31; }
      contentY += 10;
    }
    if (price != null) { ctx.fillStyle = "#ffd600"; ctx.font = "800 26px sans-serif"; ctx.textAlign = "right"; ctx.fillText(money(price), 975, y + 80); ctx.textAlign = "left"; }
    y += height + 54;
  };
  if (order.concern) section(order.concern.startsWith("По результатам диагностики №") ? "Выявлено при диагностике" : "Обращение клиента", order.concern, undefined, order.concern.startsWith("По результатам диагностики №"));
  if (order.description) section("Выполненные работы", order.description, order.labor_revenue || undefined);
  if (order.recommendations) section("Рекомендации", order.recommendations);

  if (parts.length) {
    ctx.fillStyle = "#fff"; ctx.font = "900 23px sans-serif"; ctx.fillText("ЗАПЧАСТИ", 68, y + 22); y += 42;
    let currentCategory = -1;
    for (const part of parts) {
      const category = partCategory(part.name);
      if (category !== currentCategory) {
        currentCategory = category;
        ctx.fillStyle = "#96a1ad"; ctx.font = "800 15px sans-serif";
        ctx.fillText(partCategoryLabels[category] ?? partCategoryLabels[6]!, 76, y + 17);
        y += 30;
      }
      const quantity = Math.max(1, Number(part.quantity || 1));
      const unitCost = Number(part.unit_cost || 0);
      const saleUnit = unitCost && part.markup_percent != null ? Math.ceil((unitCost * (1 + Number(part.markup_percent) / 100)) / 50) * 50 : null;
      panel(y, 78);
      drawPartIcon(ctx, part.name, 98, y + 39);
      ctx.fillStyle = "#fff"; ctx.font = "700 21px sans-serif"; ctx.fillText(part.name, 128, y + 31);
      ctx.fillStyle = "#96a1ad"; ctx.font = "500 17px sans-serif"; ctx.fillText([`${quantity} шт.`, saleUnit ? `${money(saleUnit)} / шт.` : null].filter(Boolean).join(" · "), 128, y + 58);
      if (saleUnit) { ctx.fillStyle = "#fff"; ctx.font = "800 24px sans-serif"; ctx.textAlign = "right"; ctx.fillText(money(saleUnit * quantity), 975, y + 48); ctx.textAlign = "left"; }
      y += 90;
    }
    y += 20;
  } else if (order.parts_revenue) {
    section("Запчасти", "Запчасти по заказ-наряду", order.parts_revenue);
  }

  const total = order.labor_revenue + order.parts_revenue;
  panel(y, 168);
  const priceLine = (label: string, amount: number, top: number) => { ctx.fillStyle = "#96a1ad"; ctx.font = "600 21px sans-serif"; ctx.textAlign = "left"; ctx.fillText(label, 103, top); ctx.fillStyle = "#fff"; ctx.font = "800 25px sans-serif"; ctx.textAlign = "right"; ctx.fillText(money(amount), 975, top); };
  if (order.labor_revenue) priceLine("Работы", order.labor_revenue, y + 36);
  if (order.parts_revenue) priceLine("Запчасти", order.parts_revenue, y + 68);
  ctx.fillStyle = "#fff"; ctx.font = "900 27px sans-serif"; ctx.textAlign = "left"; ctx.fillText("ИТОГО К ОПЛАТЕ", 103, y + 128);
  ctx.fillStyle = "#ffd600"; ctx.font = "900 44px sans-serif"; ctx.textAlign = "right"; ctx.fillText(money(total), 975, y + 134); ctx.textAlign = "left";
  drawApexThanksFooter(ctx, canvas.width, canvas.height - 44);
  return canvas;
}

function canvasBlob(canvas: HTMLCanvasElement, type: "image/png" | "image/jpeg", quality?: number) {
  return new Promise<Blob>((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error("Не удалось создать изображение")), type, quality));
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = filename; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function exportOrderImage(order: Order, share: boolean) {
  const canvas = await renderOrderCanvas(order);
  const blob = await canvasBlob(canvas, "image/png");
  const file = new File([blob], `zakaz-naryad-${order.id}.png`, { type: "image/png" });
  if (share && navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] }))) { await navigator.share({ title: `Заказ-наряд №${order.id}`, files: [file] }); return; }
  download(blob, file.name);
}

const bytes = (value: string) => new TextEncoder().encode(value);
function joinBytes(parts: Uint8Array[]) { const size = parts.reduce((sum, part) => sum + part.length, 0); const result = new Uint8Array(size); let offset = 0; for (const part of parts) { result.set(part, offset); offset += part.length; } return result; }

async function canvasPdf(canvas: HTMLCanvasElement) {
  const jpeg = new Uint8Array(await (await canvasBlob(canvas, "image/jpeg", 0.92)).arrayBuffer());
  const pageWidth = 595; const pageHeight = 842; const imageHeight = canvas.height * pageWidth / canvas.width;
  const pageCount = Math.max(1, Math.ceil(imageHeight / pageHeight)); const imageId = 3 + pageCount; const firstContentId = imageId + 1;
  const objects: (Uint8Array | undefined)[] = Array.from(
    { length: 3 + pageCount * 2 + 1 },
    () => undefined,
  );
  objects[1] = bytes("<< /Type /Catalog /Pages 2 0 R >>");
  objects[2] = bytes(`<< /Type /Pages /Kids [${Array.from({ length: pageCount }, (_, index) => `${3 + index} 0 R`).join(" ")}] /Count ${pageCount} >>`);
  for (let index = 0; index < pageCount; index++) objects[3 + index] = bytes(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /XObject << /Im0 ${imageId} 0 R >> >> /Contents ${firstContentId + index} 0 R >>`);
  objects[imageId] = joinBytes([bytes(`<< /Type /XObject /Subtype /Image /Width ${canvas.width} /Height ${canvas.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`), jpeg, bytes("\nendstream")]);
  for (let index = 0; index < pageCount; index++) { const y = pageHeight - imageHeight + index * pageHeight; const command = `q ${pageWidth} 0 0 ${imageHeight.toFixed(3)} 0 ${y.toFixed(3)} cm /Im0 Do Q`; objects[firstContentId + index] = bytes(`<< /Length ${command.length} >>\nstream\n${command}\nendstream`); }
  const chunks: Uint8Array[] = [bytes("%PDF-1.4\n%APEX\n")]; const offsets = [0]; let offset = chunks[0]!.length;
  for (let id = 1; id < objects.length; id++) { offsets[id] = offset; const object = joinBytes([bytes(`${id} 0 obj\n`), objects[id]!, bytes("\nendobj\n")]); chunks.push(object); offset += object.length; }
  const xrefOffset = offset; const xref = [`xref\n0 ${objects.length}\n0000000000 65535 f \n`, ...offsets.slice(1).map((value) => `${String(value).padStart(10, "0")} 00000 n \n`)].join("");
  chunks.push(bytes(xref), bytes(`trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`));
  return new Blob(chunks as BlobPart[], { type: "application/pdf" });
}

export async function exportOrderPdf(order: Order) {
  const canvas = await renderOrderCanvas(order);
  download(await canvasPdf(canvas), `zakaz-naryad-${order.id}.pdf`);
}
