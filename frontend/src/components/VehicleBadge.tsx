type VehicleProfile = "compact" | "sedan" | "wagon" | "crossover" | "suv" | "van" | "pickup";

const modelProfiles: Array<[RegExp, VehicleProfile]> = [
  [/(уаз|patriot|land cruiser|prado|wrangler|defender|g-class|гелик|tahoe|escalade|pajero|montero|discovery)/i, "suv"],
  [/(transit|sprinter|газель|gazelle|caddy|multivan|caravelle|vito|v-class|porter|jumper|ducato|boxer|expert|jumpy|trafic|master|crafter)/i, "van"],
  [/(hilux|ranger|amarok|l200|d-max|navara|f-150|raptor|ram)/i, "pickup"],
  [/(octavia|largus|vesta sw|ceed sw|focus wagon|passat variant|a4 avant|a6 avant|e-class estate|superb combi|volvo v|legacy|outback|corolla fielder)/i, "wagon"],
  [/(tiguan|touareg|kodiaq|karoq|rav[ -]?4|highlander|duster|arkana|captur|koleos|qashqai|x-?trail|juke|terrano|sportage|sorento|seltos|tucson|santa fe|creta|palisade|cx-[3579]|outlander|asx|forester|crosstrek|cayenne|macan|q[3578]\b|x[3567]\b|gle|glc|gls|gla|haval|geely|exeed|omoda|chery tiggo|changan cs|jetour|tank)/i, "crossover"],
  [/(polo|golf|focus|fiesta|rio|solaris|ceed|i30|i20|corsa|astra|yaris|fabia|swift|micra|mazda ?3|civic|granta|kalina|priora|211[0-5]|210[89]|logan|sandero|clio)/i, "compact"],
];

const brandCodes: Record<string, string> = {
  lada: "L", ваз: "В", vazon: "В", kia: "K", hyundai: "H", toyota: "T", lexus: "L", nissan: "N", honda: "H", mazda: "M", mitsubishi: "M", subaru: "S", suzuki: "S", ford: "F", chevrolet: "C", volkswagen: "VW", vw: "VW", skoda: "Š", renault: "R", bmw: "BMW", mercedes: "M", audi: "A", volvo: "V", porsche: "P", geely: "G", haval: "H", chery: "C", exeed: "E", omoda: "O", changan: "C", uaz: "У", уаз: "У",
};

const profiles: Record<VehicleProfile, { body: string; glass: string }> = {
  compact: { body: "M7 39 12 29h8l8-9h14l9 9h7l5 10v4H7Z", glass: "M25 29l5-6h10l6 6Z" },
  sedan: { body: "M5 39 11 30h10l9-10h17l10 10h7l5 9v4H5Z", glass: "M28 30l5-7h12l7 7Z" },
  wagon: { body: "M5 39 11 30h8l9-10h25l8 10h5l5 9v4H5Z", glass: "M27 30l5-7h20l6 7Z" },
  crossover: { body: "M5 39 10 29h10l8-12h19l11 12h7l5 10v4H5Z", glass: "M27 29l5-9h13l8 9Z" },
  suv: { body: "M4 39 9 28h10l7-14h22l11 14h7l5 11v4H4Z", glass: "M26 28l4-11h16l9 11Z" },
  van: { body: "M5 39 10 22h26l14 8h10l7 9v4H5Z", glass: "M14 29l3-5h17l8 5Z" },
  pickup: { body: "M5 39 11 30h10l8-11h17l9 11h11l5 9v4H5Z", glass: "M28 30l4-8h12l7 8Z" },
};

function getProfile(model: string): VehicleProfile {
  return modelProfiles.find(([match]) => match.test(model))?.[1] ?? "sedan";
}

function getBrandCode(brand: string) {
  const key = brand.trim().toLocaleLowerCase("ru");
  return brandCodes[key] || brand.trim().slice(0, 2).toLocaleUpperCase("ru") || "АВ";
}

export function VehicleBadge({ brand, model }: { brand: string; model: string }) {
  const shape = profiles[getProfile(model)];
  return <span className="grid size-12 shrink-0 place-items-center overflow-hidden rounded-xl border border-apex/30 bg-gradient-to-br from-apex/15 to-panel-soft text-apex" title={`${brand} ${model}`}>
    <svg viewBox="0 0 72 58" className="h-11 w-11" role="img" aria-label={`${brand} ${model}`}>
      <text x="7" y="12" fill="currentColor" fontSize="8" fontWeight="800" letterSpacing=".4">{getBrandCode(brand)}</text>
      <path d={shape.body} fill="currentColor" fillOpacity=".11" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d={shape.glass} fill="none" stroke="currentColor" strokeOpacity=".8" strokeWidth="1.25" strokeLinejoin="round" />
      <path d="M13 39h8m32 0h9" stroke="currentColor" strokeLinecap="round" />
      <circle cx="20" cy="43" r="5" fill="#0b121a" stroke="currentColor" strokeWidth="1.5" /><circle cx="20" cy="43" r="1.5" fill="currentColor" />
      <circle cx="54" cy="43" r="5" fill="#0b121a" stroke="currentColor" strokeWidth="1.5" /><circle cx="54" cy="43" r="1.5" fill="currentColor" />
    </svg>
  </span>;
}
