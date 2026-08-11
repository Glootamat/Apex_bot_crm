import { describe, expect, it } from "vitest";
import type { Order } from "../lib/types";
import { calculateFinance } from "../lib/finance";

const order = (value: Partial<Order>): Order => ({
  id: 1, car_id: 1, description: "Работы", labor_revenue: 0, parts_cost: 0,
  parts_revenue: 0, parts_profit: 0, status: "ready", created_at: "2026-01-01 10:00:00",
  brand: "Lada", model: "Vesta", plate_number: null, vin: null, mileage: null,
  customer_name: null, concern: null, agreed_amount: null, recommendations: null,
  completed_at: "2026-01-01 11:00:00", archived_at: null, parts_source: null,
  mileage_at_visit: null, profit: 0, ...value,
});

describe("finance calculation", () => {
  it("does not subtract receipt purchases before a sale price is assigned", () => {
    const pending = order({ id: 1, parts_cost: 1_000, profit: 0 });
    const sold = order({ id: 2, parts_cost: 1_000, parts_revenue: 1_500, profit: 500 });
    expect(calculateFinance([pending, sold]).markup).toBe(500);
    expect(calculateFinance([pending, sold]).profit).toBe(500);
  });
});
