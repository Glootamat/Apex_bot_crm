import { describe, expect, it } from "vitest";
import { carName, customerName, formatDateTime, money, parseCrmDate, statusLabel } from "./format";

describe("CRM formatting", () => {
  it("shows a neutral label for generated or empty customer names", () => {
    expect(customerName("Клиент +79001234567")).toBe("Имя не указано");
    expect(customerName(" ")).toBe("Имя не указано");
    expect(customerName("Александр")).toBe("Александр");
  });

  it("formats car, status and money for the Russian interface", () => {
    expect(carName({ brand: "Nissan", model: "Teana", plate_number: "A123BC" })).toBe("Nissan Teana · A123BC");
    expect(statusLabel("in_progress")).toBe("В работе");
    expect(money(12500)).toContain("12");
  });

  it("always displays database timestamps and appointments in Moscow time", () => {
    expect(formatDateTime("2026-08-09 12:00:00")).toContain("15:00");
    expect(parseCrmDate("2026-08-09T15:00").toISOString()).toBe("2026-08-09T12:00:00.000Z");
  });
});
