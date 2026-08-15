export type LaborCategory = "ТО и масла" | "Тормозная система" | "Ходовая часть" | "Двигатель" | "Электрика";

export type LaborStandard = {
  id: string;
  name: string;
  category: LaborCategory;
  hours: number;
  applicability: string;
  unit: string;
};

export type LaborMarketReference = {
  priceMin: number;
  priceMax: number;
  publicHoursMin?: number;
  sourceIds: Array<keyof typeof laborSources>;
};

export const laborSources = {
  virbac: { title: "ВИРБАКавто, Ставрополь", url: "https://stavropol.virbacavto.ru/service/katalog-uslug/" },
  abrand: { title: "А-Бренд, Ставрополь", url: "https://autoservice126.ru/" },
  avangard: { title: "Авангард, Ставрополь", url: "https://avtoservisavangardstav.ru/page16" },
  fresh: { title: "Fresh Сервис, Ставрополь", url: "https://2gis.ru/stavropol/firm/70000001056384916/tab/prices" },
  localrepair: { title: "Публичные прайсы СТО Ставрополя", url: "https://stavropol.localrepair.ru/sto/" },
  fit: { title: "FIT SERVICE, Ставрополь", url: "https://stavropol.fitauto.ru/services/" },
} as const;

export const laborMarketCheckedAt = "15.08.2026";

export const laborCategories: LaborCategory[] = ["ТО и масла", "Тормозная система", "Ходовая часть", "Двигатель", "Электрика"];

export const laborStandards: LaborStandard[] = [
  { id: "oil-engine", name: "Замена моторного масла и масляного фильтра", category: "ТО и масла", hours: 0.5, applicability: "Все автомобили", unit: "комплекс" },
  { id: "filter-air", name: "Замена воздушного фильтра", category: "ТО и масла", hours: 0.2, applicability: "Все автомобили", unit: "1 шт." },
  { id: "filter-cabin", name: "Замена салонного фильтра", category: "ТО и масла", hours: 0.3, applicability: "Все автомобили", unit: "1 шт." },
  { id: "plugs", name: "Замена свечей зажигания", category: "ТО и масла", hours: 0.6, applicability: "Рядный 4-цилиндровый двигатель", unit: "комплект" },
  { id: "coolant", name: "Замена охлаждающей жидкости", category: "ТО и масла", hours: 0.8, applicability: "Все автомобили", unit: "система" },
  { id: "brake-fluid", name: "Замена тормозной жидкости", category: "ТО и масла", hours: 0.8, applicability: "Все автомобили", unit: "система" },
  { id: "oil-mt", name: "Замена масла в МКПП", category: "ТО и масла", hours: 0.6, applicability: "МКПП", unit: "коробка" },
  { id: "oil-at", name: "Частичная замена масла в АКПП", category: "ТО и масла", hours: 1, applicability: "АКПП", unit: "коробка" },
  { id: "pads-front", name: "Замена передних тормозных колодок", category: "Тормозная система", hours: 0.8, applicability: "Все автомобили", unit: "комплект на ось" },
  { id: "pads-rear-disc", name: "Замена задних тормозных колодок", category: "Тормозная система", hours: 0.9, applicability: "Дисковые тормоза", unit: "комплект на ось" },
  { id: "pads-rear-drum", name: "Замена задних барабанных колодок", category: "Тормозная система", hours: 1.5, applicability: "Барабанные тормоза", unit: "комплект на ось" },
  { id: "discs-front", name: "Замена передних тормозных дисков", category: "Тормозная система", hours: 1.4, applicability: "Все автомобили", unit: "пара" },
  { id: "discs-rear", name: "Замена задних тормозных дисков", category: "Тормозная система", hours: 1.6, applicability: "Дисковые тормоза", unit: "пара" },
  { id: "drums-rear", name: "Замена задних тормозных барабанов", category: "Тормозная система", hours: 1.4, applicability: "Барабанные тормоза", unit: "пара" },
  { id: "caliper", name: "Замена тормозного суппорта", category: "Тормозная система", hours: 0.8, applicability: "Все автомобили", unit: "1 сторона" },
  { id: "caliper-service", name: "Обслуживание направляющих суппорта", category: "Тормозная система", hours: 0.5, applicability: "Все автомобили", unit: "1 ось" },
  { id: "tie-end", name: "Замена рулевого наконечника", category: "Ходовая часть", hours: 0.6, applicability: "Все автомобили", unit: "1 сторона" },
  { id: "tie-rod", name: "Замена рулевой тяги", category: "Ходовая часть", hours: 1, applicability: "Все автомобили", unit: "1 сторона" },
  { id: "ball-joint", name: "Замена шаровой опоры", category: "Ходовая часть", hours: 1, applicability: "Без перепрессовки", unit: "1 сторона" },
  { id: "stabilizer-link", name: "Замена стойки стабилизатора", category: "Ходовая часть", hours: 0.5, applicability: "Все автомобили", unit: "1 сторона" },
  { id: "stabilizer-bushes", name: "Замена втулок стабилизатора", category: "Ходовая часть", hours: 1, applicability: "Все автомобили", unit: "комплект на ось" },
  { id: "shock-front", name: "Замена переднего амортизатора / стойки", category: "Ходовая часть", hours: 1.6, applicability: "Стойка типа McPherson", unit: "1 сторона" },
  { id: "shock-rear", name: "Замена заднего амортизатора", category: "Ходовая часть", hours: 0.7, applicability: "Все автомобили", unit: "1 сторона" },
  { id: "bearing-front", name: "Замена переднего ступичного подшипника", category: "Ходовая часть", hours: 1.8, applicability: "С перепрессовкой", unit: "1 сторона" },
  { id: "hub-front", name: "Замена передней ступицы в сборе", category: "Ходовая часть", hours: 1.2, applicability: "Ступица в сборе", unit: "1 сторона" },
  { id: "cv-boot", name: "Замена пыльника наружного ШРУС", category: "Ходовая часть", hours: 1.5, applicability: "Передний привод", unit: "1 сторона" },
  { id: "cv-joint", name: "Замена наружного ШРУС", category: "Ходовая часть", hours: 1.4, applicability: "Передний привод", unit: "1 сторона" },
  { id: "belt-aux", name: "Замена ремня навесного оборудования", category: "Двигатель", hours: 0.7, applicability: "Без снятия дополнительных узлов", unit: "1 ремень" },
  { id: "timing-belt", name: "Замена комплекта ремня ГРМ", category: "Двигатель", hours: 3.2, applicability: "Рядный 4-цилиндровый двигатель", unit: "комплект" },
  { id: "valve-cover", name: "Замена прокладки клапанной крышки", category: "Двигатель", hours: 1.2, applicability: "Рядный 4-цилиндровый двигатель", unit: "1 шт." },
  { id: "front-crank-seal", name: "Замена переднего сальника коленвала", category: "Двигатель", hours: 2.8, applicability: "Без снятия двигателя", unit: "1 шт." },
  { id: "rear-crank-seal", name: "Замена заднего сальника коленвала", category: "Двигатель", hours: 5.5, applicability: "Со снятием КПП", unit: "1 шт." },
  { id: "engine-diagnostics", name: "Компьютерная диагностика двигателя", category: "Двигатель", hours: 0.7, applicability: "OBD-II", unit: "диагностика" },
  { id: "battery", name: "Замена аккумулятора", category: "Электрика", hours: 0.3, applicability: "Без регистрации в блоке управления", unit: "1 шт." },
  { id: "starter", name: "Снятие и установка стартера", category: "Электрика", hours: 1.5, applicability: "Без снятия дополнительных узлов", unit: "1 шт." },
  { id: "alternator", name: "Снятие и установка генератора", category: "Электрика", hours: 1.7, applicability: "Без снятия дополнительных узлов", unit: "1 шт." },
  { id: "fuel-pump", name: "Замена бензонасоса", category: "Электрика", hours: 1.4, applicability: "Доступ из салона", unit: "1 шт." },
  { id: "lamp", name: "Замена лампы наружного освещения", category: "Электрика", hours: 0.3, applicability: "Без снятия бампера и фары", unit: "1 шт." },
  { id: "electric-diagnostics", name: "Диагностика электрооборудования", category: "Электрика", hours: 1, applicability: "Первичная диагностика", unit: "диагностика" },
];

export const laborMarket: Partial<Record<string, LaborMarketReference>> = {
  "oil-engine": { priceMin: 500, priceMax: 790, publicHoursMin: .5, sourceIds: ["virbac", "abrand", "avangard"] },
  "filter-air": { priceMin: 300, priceMax: 520, publicHoursMin: .17, sourceIds: ["virbac", "abrand", "avangard", "fresh"] },
  "filter-cabin": { priceMin: 300, priceMax: 570, publicHoursMin: .25, sourceIds: ["virbac", "abrand", "avangard"] },
  "plugs": { priceMin: 390, priceMax: 1200, publicHoursMin: .5, sourceIds: ["virbac", "abrand", "avangard", "localrepair"] },
  "coolant": { priceMin: 1400, priceMax: 2300, publicHoursMin: 2, sourceIds: ["virbac", "abrand", "localrepair"] },
  "brake-fluid": { priceMin: 900, priceMax: 1980, publicHoursMin: .5, sourceIds: ["virbac", "abrand", "avangard", "fresh"] },
  "oil-mt": { priceMin: 490, priceMax: 680, publicHoursMin: .5, sourceIds: ["abrand", "avangard", "localrepair"] },
  "oil-at": { priceMin: 1300, priceMax: 4950, publicHoursMin: .5, sourceIds: ["virbac", "abrand", "avangard", "fresh"] },
  "pads-front": { priceMin: 600, priceMax: 1760, publicHoursMin: .5, sourceIds: ["virbac", "abrand", "avangard", "fresh"] },
  "pads-rear-disc": { priceMin: 800, priceMax: 1140, publicHoursMin: .5, sourceIds: ["virbac", "avangard"] },
  "pads-rear-drum": { priceMin: 1140, priceMax: 1700, publicHoursMin: .5, sourceIds: ["virbac", "avangard"] },
  "discs-front": { priceMin: 680, priceMax: 2000, publicHoursMin: .5, sourceIds: ["virbac", "abrand", "avangard"] },
  "discs-rear": { priceMin: 680, priceMax: 2000, publicHoursMin: .5, sourceIds: ["virbac", "abrand", "avangard"] },
  "caliper": { priceMin: 1000, priceMax: 1400, sourceIds: ["abrand"] },
  "tie-end": { priceMin: 400, priceMax: 600, sourceIds: ["abrand", "avangard"] },
  "tie-rod": { priceMin: 800, priceMax: 1200, publicHoursMin: 1, sourceIds: ["virbac", "abrand", "avangard"] },
  "ball-joint": { priceMin: 400, priceMax: 1000, sourceIds: ["abrand"] },
  "stabilizer-link": { priceMin: 400, priceMax: 700, sourceIds: ["abrand", "avangard"] },
  "stabilizer-bushes": { priceMin: 600, priceMax: 1000, sourceIds: ["abrand", "avangard"] },
  "shock-front": { priceMin: 1300, priceMax: 2500, publicHoursMin: 1, sourceIds: ["virbac", "abrand", "avangard"] },
  "shock-rear": { priceMin: 800, priceMax: 2500, sourceIds: ["abrand", "avangard"] },
  "bearing-front": { priceMin: 1400, priceMax: 3000, publicHoursMin: .5, sourceIds: ["virbac", "abrand", "localrepair"] },
  "hub-front": { priceMin: 1400, priceMax: 3000, publicHoursMin: .5, sourceIds: ["virbac", "abrand"] },
  "cv-boot": { priceMin: 600, priceMax: 2190, sourceIds: ["fit", "localrepair"] },
  "cv-joint": { priceMin: 860, priceMax: 2000, sourceIds: ["abrand", "avangard", "localrepair"] },
  "belt-aux": { priceMin: 700, priceMax: 1200, sourceIds: ["abrand", "avangard"] },
  "timing-belt": { priceMin: 2500, priceMax: 8000, publicHoursMin: 1.5, sourceIds: ["virbac", "abrand", "avangard", "localrepair"] },
  "valve-cover": { priceMin: 1200, priceMax: 1200, sourceIds: ["avangard"] },
  "front-crank-seal": { priceMin: 700, priceMax: 700, sourceIds: ["localrepair"] },
  "rear-crank-seal": { priceMin: 2200, priceMax: 4000, sourceIds: ["localrepair"] },
  "engine-diagnostics": { priceMin: 1210, priceMax: 1400, sourceIds: ["abrand", "fresh"] },
  "battery": { priceMin: 250, priceMax: 300, publicHoursMin: .25, sourceIds: ["virbac", "abrand", "localrepair"] },
  "starter": { priceMin: 1200, priceMax: 2000, sourceIds: ["avangard", "localrepair"] },
  "alternator": { priceMin: 2000, priceMax: 2000, sourceIds: ["avangard"] },
  "fuel-pump": { priceMin: 1800, priceMax: 2000, sourceIds: ["abrand", "avangard"] },
  "lamp": { priceMin: 200, priceMax: 600, sourceIds: ["abrand", "avangard"] },
  "electric-diagnostics": { priceMin: 600, priceMax: 1400, sourceIds: ["abrand", "fresh"] },
};
