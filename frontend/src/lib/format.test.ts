import { describe, expect, it } from "vitest";
import { carName, customerName, money, statusLabel } from "./format";

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
});
