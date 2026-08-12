type BodyStyle = "sedan" | "hatchback" | "wagon" | "suv" | "pickup" | "van";

const bodyRules: Array<[RegExp, BodyStyle]> = [
  [/(cayenne|q[3578]\b|x[3567]\b|gle|glc|gls|gla|tiguan|touareg|kodiaq|karoq|rav[ -]?4|highlander|land cruiser|prado|duster|arkana|captur|koleos|qashqai|x-?trail|juke|terrano|sportage|sorento|seltos|tucson|santa fe|creta|palisade|cx-[3579]|outlander|asx|forester|crosstrek|wrangler|grand cherokee|changan cs|haval|geely|exeed|omoda|chery tiggo|уаз)/i, "suv"],
  [/(transit|sprinter|gazelle|газель|caddy|multivan|caravelle|vito|porter|jumper|ducato|boxer)/i, "van"],
  [/(hilux|ranger|amarok|l200|d-max|navara|f-150|ram)/i, "pickup"],
  [/(octavia|vesta sw|largus|ceed sw|focus wagon|passat variant|a4 avant|a6 avant|e-class estate|superb combi|volvo v|legacy)/i, "wagon"],
  [/(golf|polo|focus|fiesta|rio|solaris|ceed|cerato|i30|i20|corsa|astra|yaris|fabia|swift|micra|mazda 3|civic|granta|kalina|211[0-5]|210[89])/i, "hatchback"],
];

function bodyStyle(model: string): BodyStyle {
  return bodyRules.find(([rule]) => rule.test(model))?.[1] ?? "sedan";
}

function brandMark(brand: string) {
  return brand.trim().slice(0, 2).toLocaleUpperCase("ru") || "АВ";
}

const silhouettes: Record<BodyStyle, { roof: string; rear: string }> = {
  sedan: { roof: "M64 72 91 43h53l30 29", rear: "L189 72h17l12 20" },
  hatchback: { roof: "M61 72 90 43h48l35 29", rear: "L173 72h27l9 20" },
  wagon: { roof: "M55 72 84 43h75l29 29", rear: "L188 72h18l8 20" },
  suv: { roof: "M53 73 82 36h66l35 37", rear: "L183 73h21l11 23" },
  pickup: { roof: "M48 75 79 44h52l26 31", rear: "L157 75h42l11 21" },
  van: { roof: "M45 76 69 34h74l25 42", rear: "L168 76h34l9 20" },
};

export function VehicleIllustration({ brand, model }: { brand: string; model: string }) {
  const type = bodyStyle(model);
  const silhouette = silhouettes[type];
  return <div className="relative overflow-hidden rounded-2xl border border-line bg-gradient-to-br from-panel-soft via-panel to-canvas px-3 pt-2">
    <div className="absolute right-3 top-3 rounded-lg border border-line/80 bg-canvas/70 px-2 py-1 text-[10px] font-black tracking-wide text-muted">{brandMark(brand)}</div>
    <svg viewBox="0 0 240 118" className="mx-auto block h-28 w-full max-w-sm text-apex" role="img" aria-label={`${brand} ${model}, ${type}`}>
      <path d="M25 96h190" stroke="currentColor" strokeOpacity=".2" strokeWidth="2" />
      <path d={`M30 95 42 73h19 ${silhouette.roof} ${silhouette.rear} 8 3 8 15v10H30Z`} fill="currentColor" fillOpacity=".2" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" />
      <path d="M76 72h75" stroke="currentColor" strokeOpacity=".7" strokeWidth="2" />
      <path d="M93 46v26M143 46v26" stroke="currentColor" strokeOpacity=".45" strokeWidth="2" />
      <circle cx="67" cy="96" r="14" fill="#0b121a" stroke="currentColor" strokeWidth="3" /><circle cx="67" cy="96" r="5" fill="currentColor" />
      <circle cx="177" cy="96" r="14" fill="#0b121a" stroke="currentColor" strokeWidth="3" /><circle cx="177" cy="96" r="5" fill="currentColor" />
      <path d="M36 80h17M190 80h15" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
    <p className="-mt-2 pb-2 text-center text-[10px] font-bold uppercase tracking-wide text-muted">{type === "suv" ? "Кроссовер / внедорожник" : type === "wagon" ? "Универсал" : type === "hatchback" ? "Хэтчбек" : type === "pickup" ? "Пикап" : type === "van" ? "Фургон / минивэн" : "Седан"}</p>
  </div>;
}
