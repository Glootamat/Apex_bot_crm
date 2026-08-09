import { describe, expect, it } from "vitest";
import { containSize, orderCustomerLabel } from "./orderImage";

describe("order image", () => {
  it("keeps the logo aspect ratio", () => {
    expect(containSize(679, 679, 150, 125)).toEqual({ width: 125, height: 125 });
    expect(containSize(800, 400, 150, 125)).toEqual({ width: 150, height: 75 });
  });

  it("does not show the car name as the customer", () => {
    expect(orderCustomerLabel({ customer_name: "Kia Venga", brand: "Kia", model: "Venga" })).toBe("Не указан");
    expect(orderCustomerLabel({ customer_name: "Иван Петров", brand: "Kia", model: "Venga" })).toBe("Иван Петров");
  });
});
