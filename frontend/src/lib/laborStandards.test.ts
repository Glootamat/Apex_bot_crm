import { describe, expect, it } from "vitest";
import { laborCategories, laborStandards } from "./laborStandards";

describe("labor standards starter catalog", () => {
  it("contains unique, valid operations in every category", () => {
    expect(new Set(laborStandards.map((item) => item.id)).size).toBe(laborStandards.length);
    expect(laborStandards.every((item) => item.hours > 0)).toBe(true);
    for (const category of laborCategories) expect(laborStandards.some((item) => item.category === category)).toBe(true);
  });

  it("treats brake pads and discs as axle sets or pairs", () => {
    const paired = laborStandards.filter((item) => /колодок|тормозных дисков|тормозных барабанов/i.test(item.name));
    expect(paired.length).toBeGreaterThan(0);
    expect(paired.every((item) => /ось|пара/.test(item.unit))).toBe(true);
  });
});
