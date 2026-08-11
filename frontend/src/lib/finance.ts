import type { Order } from "./types";

export function calculateFinance(orders: Order[]) {
  const labor = orders.reduce((sum, order) => sum + order.labor_revenue, 0);
  const partsRevenue = orders.reduce((sum, order) => sum + order.parts_revenue, 0);
  const partsCost = orders.reduce((sum, order) => sum + order.parts_cost, 0);
  const extraPartsProfit = orders.reduce((sum, order) => sum + order.parts_profit, 0);
  const markup = orders.reduce(
    (sum, order) => sum + (
      order.parts_revenue === 0
        ? order.parts_profit
        : order.parts_revenue - order.parts_cost + order.parts_profit
    ),
    0,
  );
  return {
    count: orders.length,
    labor,
    partsRevenue,
    partsCost,
    extraPartsProfit,
    markup,
    revenue: labor + partsRevenue,
    profit: orders.reduce((sum, order) => sum + order.profit, 0),
  };
}
