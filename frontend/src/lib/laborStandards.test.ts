import { describe, expect, it } from "vitest";
import { laborCategories, laborMarket, laborSources, laborStandards } from "./laborStandards";

describe("labor standards starter catalog", () => {
  it("contains unique, valid operations in every category", () => {
    expect(laborStandards.length).toBeGreaterThanOrEqual(150);
    expect(new Set(laborStandards.map((item) => item.id)).size).toBe(laborStandards.length);
    expect(laborStandards.every((item) => item.hours > 0)).toBe(true);
    for (const category of laborCategories) expect(laborStandards.some((item) => item.category === category)).toBe(true);
  });

  it("treats brake pads and discs as axle sets or pairs", () => {
    const paired = laborStandards.filter((item) => /колодок|тормозных дисков|тормозных барабанов/i.test(item.name));
    expect(paired.length).toBeGreaterThan(0);
    expect(paired.every((item) => /ось|пара/.test(item.unit))).toBe(true);
  });

  it("keeps every market reference traceable and internally consistent", () => {
    expect(Object.keys(laborMarket).length).toBeGreaterThanOrEqual(90);
    const operationIds = new Set(laborStandards.map((item) => item.id));
    for (const [id, reference] of Object.entries(laborMarket)) {
      if (!reference) throw new Error(`Missing market reference for ${id}`);
      expect(operationIds.has(id)).toBe(true);
      expect(reference.priceMin).toBeGreaterThan(0);
      expect(reference.priceMax).toBeGreaterThanOrEqual(reference.priceMin);
      expect(reference.sourceIds.length).toBeGreaterThan(0);
      for (const sourceId of reference.sourceIds) expect(laborSources[sourceId].url).toMatch(/^https:\/\//);
    }
  });
});
