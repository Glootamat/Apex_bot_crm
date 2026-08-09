let approvedLogo: Promise<HTMLImageElement> | null = null;

function loadApprovedLogo() {
  approvedLogo ??= new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = "/assets/brand/apex-report-logo-approved.png";
  });
  return approvedLogo;
}

export async function drawApexReportBrand(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width = 450,
) {
  const image = await loadApprovedLogo();
  // Crop the approved lockup from its original concept sheet without redrawing it.
  const sx = image.naturalWidth * 0.095;
  const sy = image.naturalHeight * 0.24;
  const sw = image.naturalWidth * 0.81;
  const sh = image.naturalHeight * 0.48;
  const height = width * (sh / sw);
  ctx.drawImage(image, sx, sy, sw, sh, x, y, width, height);
}

export function drawApexThanksFooter(ctx: CanvasRenderingContext2D, canvasWidth: number, y: number) {
  const label = "Спасибо, что выбрали Apex Auto";
  ctx.save();
  ctx.font = "500 20px sans-serif";
  const textWidth = ctx.measureText(label).width;
  const groupWidth = 48 + textWidth;
  const startX = (canvasWidth - groupWidth) / 2;
  const cx = startX + 20;
  ctx.strokeStyle = "#3a4652";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(cx, y, 20, 0, Math.PI * 2);
  ctx.stroke();
  ctx.strokeStyle = "#ffd600";
  ctx.lineWidth = 3;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(cx - 9, y);
  ctx.lineTo(cx - 2, y + 7);
  ctx.lineTo(cx + 10, y - 7);
  ctx.stroke();
  ctx.fillStyle = "#a7afb9";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(label, startX + 48, y);
  ctx.restore();
}
