import type { Diagnostic, DiagnosticItem } from "./types";
import { customerName, money } from "./format";
import { drawApexReportBrand, drawApexThanksFooter } from "./brandCanvas";

function worst(item: DiagnosticItem) {
  const values = [item.status, item.left_status, item.right_status];
  return values.includes("critical") ? "critical" : values.includes("attention") ? "attention" : "ok";
}

function issueRows(item: DiagnosticItem): DiagnosticItem[] {
  if (item.left_status !== null || item.right_status !== null) {
    const rows: DiagnosticItem[] = [];
    if (item.left_status && ["attention", "critical"].includes(item.left_status)) rows.push({ ...item, label: `${item.label} — левая сторона`, status: item.left_status, left_status: null, right_status: null });
    if (item.right_status && ["attention", "critical"].includes(item.right_status)) rows.push({ ...item, label: `${item.label} — правая сторона`, status: item.right_status, left_status: null, right_status: null });
    return rows;
  }
  return ["attention", "critical"].includes(item.status) ? [item] : [];
}

function textLines(ctx: CanvasRenderingContext2D, text: string, width: number, maxLines = 2) {
  const words = text.trim().split(/\s+/); const lines: string[] = []; let line = "";
  for (const word of words) {
    const next = `${line} ${word}`.trim();
    if (line && ctx.measureText(next).width > width) { lines.push(line); line = word; }
    else line = next;
  }
  if (line) lines.push(line);
  if (lines.length > maxLines) { lines.length = maxLines; lines[maxLines - 1] = `${lines[maxLines - 1]!.replace(/[.…]*$/, "")}…`; }
  return lines;
}

function issueHeight(item: DiagnosticItem) {
  return item.comment || item.recommendation || item.estimated_cost != null ? 106 : 76;
}

async function diagnosticBlob(value: Diagnostic) {
  const issues = value.items.flatMap(issueRows);
  const attention = issues.filter((item) => worst(item) === "attention");
  const critical = issues.filter((item) => worst(item) === "critical");
  const columnHeight = (items: DiagnosticItem[]) => items.reduce((sum, item) => sum + issueHeight(item) + 12, 0);
  const cardsBottom = 430 + Math.max(columnHeight(attention), columnHeight(critical), issues.length ? 0 : 94);
  const notesHeight = value.notes ? 100 : 0;
  const height = Math.max(650, cardsBottom + notesHeight + 62);
  const canvas = document.createElement("canvas"); canvas.width = 1080; canvas.height = height;
  const ctx = canvas.getContext("2d"); if (!ctx) throw new Error("Canvas недоступен");
  ctx.fillStyle = "#090d12"; ctx.fillRect(0, 0, canvas.width, canvas.height);

  await drawApexReportBrand(ctx, 54, 20, 370);
  ctx.textAlign = "right"; ctx.fillStyle = "#96a1ad"; ctx.font = "700 20px sans-serif";
  ctx.fillText(`ДИАГНОСТИЧЕСКАЯ КАРТА №${value.id}`, 1026, 78); ctx.textAlign = "left";

  ctx.fillStyle = "#111a23"; ctx.beginPath(); ctx.roundRect(54, 136, 972, 116, 20); ctx.fill();
  ctx.strokeStyle = "#2a3846"; ctx.lineWidth = 2; ctx.stroke();
  ctx.fillStyle = "#fff"; ctx.font = "900 39px sans-serif"; ctx.fillText(`${value.brand} ${value.model}`, 82, 184);
  ctx.fillStyle = "#96a1ad"; ctx.font = "500 20px sans-serif";
  ctx.fillText([value.plate_number, value.vin].filter(Boolean).join(" · ") || "Без госномера", 82, 216);
  ctx.textAlign = "right";
  ctx.fillText(`${customerName(value.customer_name)}${value.mileage ? ` · ${value.mileage.toLocaleString("ru-RU")} км` : ""}`, 998, 216); ctx.textAlign = "left";

  const summary = (x: number, label: string, count: number, color: string) => {
    ctx.fillStyle = "#111a23"; ctx.beginPath(); ctx.roundRect(x, 272, 476, 68, 16); ctx.fill();
    ctx.strokeStyle = "#2a3846"; ctx.stroke(); ctx.fillStyle = color; ctx.font = "900 25px sans-serif";
    ctx.fillText(String(count), x + 24, 315); ctx.fillStyle = "#fff"; ctx.font = "700 18px sans-serif"; ctx.fillText(label, x + 62, 313);
  };
  summary(54, "ТРЕБУЕТ ВНИМАНИЯ", attention.length, "#ffbd2e");
  summary(550, "НЕИСПРАВНО", critical.length, "#e34850");

  ctx.fillStyle = "#fff"; ctx.font = "900 22px sans-serif"; ctx.fillText("ВЫЯВЛЕННЫЕ ЗАМЕЧАНИЯ", 54, 380);
  const columnTitle = (x: number, label: string, color: string) => { ctx.fillStyle = color; ctx.font = "800 16px sans-serif"; ctx.fillText(label, x, 414); };
  columnTitle(54, "ТРЕБУЕТ ВНИМАНИЯ", "#ffbd2e"); columnTitle(550, "НЕИСПРАВНО", "#e34850");

  const drawIssueColumn = (items: DiagnosticItem[], x: number, color: string) => {
    let y = 430;
    for (const item of items) {
      const cardHeight = issueHeight(item); const notes = [item.comment, item.recommendation].filter(Boolean).join(" · ");
      ctx.fillStyle = "#111a23"; ctx.beginPath(); ctx.roundRect(x, y, 476, cardHeight, 16); ctx.fill();
      ctx.fillStyle = color; ctx.beginPath(); ctx.roundRect(x, y, 6, cardHeight, 4); ctx.fill();
      // Название осмотренного узла всегда белое; цвет сообщает только о статусе.
      ctx.fillStyle = "#ffffff"; ctx.font = "800 19px sans-serif";
      const lines = textLines(ctx, item.label, 424, notes || item.estimated_cost != null ? 1 : 2);
      lines.forEach((line, index) => ctx.fillText(line, x + 22, y + 30 + index * 23));
      if (notes) { ctx.fillStyle = "#96a1ad"; ctx.font = "500 16px sans-serif"; const noteLines = textLines(ctx, notes, 320, 2); noteLines.forEach((line, index) => ctx.fillText(line, x + 22, y + 62 + index * 19)); }
      if (item.estimated_cost != null) { ctx.fillStyle = "#ffd600"; ctx.font = "800 18px sans-serif"; ctx.textAlign = "right"; ctx.fillText(money(item.estimated_cost), x + 452, y + cardHeight - 20); ctx.textAlign = "left"; }
      y += cardHeight + 12;
    }
    return y;
  };
  const attentionBottom = drawIssueColumn(attention, 54, "#ffbd2e");
  const criticalBottom = drawIssueColumn(critical, 550, "#e34850");
  let contentBottom = Math.max(attentionBottom, criticalBottom);

  if (!issues.length) {
    ctx.fillStyle = "#10271f"; ctx.beginPath(); ctx.roundRect(54, 430, 972, 70, 16); ctx.fill();
    ctx.strokeStyle = "#16a36a"; ctx.stroke(); ctx.fillStyle = "#32d583"; ctx.font = "800 22px sans-serif";
    ctx.fillText("Замечаний не выявлено", 82, 474); contentBottom = 512;
  }
  if (value.notes) {
    const top = contentBottom + 8; ctx.fillStyle = "#96a1ad"; ctx.font = "800 15px sans-serif"; ctx.fillText("КОММЕНТАРИЙ МАСТЕРА", 54, top + 18);
    ctx.fillStyle = "#111a23"; ctx.beginPath(); ctx.roundRect(54, top + 30, 972, 58, 14); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = "500 18px sans-serif"; textLines(ctx, value.notes, 922, 2).forEach((line, index) => ctx.fillText(line, 78, top + 57 + index * 21));
  }
  drawApexThanksFooter(ctx, canvas.width, height - 32);
  return new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Не удалось создать изображение")), "image/png"));
}

export async function exportDiagnosticImage(value: Diagnostic, share: boolean) {
  const blob = await diagnosticBlob(value); const file = new File([blob], `diagnostika-${value.id}.png`, { type: "image/png" });
  if (share && navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] }))) { await navigator.share({ title: `Диагностическая карта №${value.id}`, files: [file] }); return; }
  const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = file.name; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}
