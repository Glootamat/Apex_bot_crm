import { Banknote, CircleDollarSign, PackageOpen, TrendingUp } from "lucide-react";
import { Card, Spinner } from "../components/ui";
import { money } from "../lib/format";
import { useCrm } from "../features/crm/useCrm";

export function FinancePage() {
  const crm = useCrm(); if (crm.isPending) return <Spinner />; const finance = crm.data?.finance;
  if (!finance) return null;
  const cards = [{ label: "Заработок сегодня", value: finance.today_profit, icon: CircleDollarSign, color: "text-apex" }, { label: "Общая выручка", value: finance.revenue, icon: Banknote, color: "text-info" }, { label: "Общая прибыль", value: finance.profit, icon: TrendingUp, color: "text-success" }, { label: "Затраты на запчасти", value: finance.parts_cost, icon: PackageOpen, color: "text-danger" }];
  return <div className="grid gap-6"><header><p className="text-sm font-bold text-apex">АНАЛИТИКА</p><h1 className="text-3xl font-black">Финансы</h1><p className="mt-1 text-muted">Финансовые показатели автосервиса</p></header><section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{cards.map(({ label, value, icon: Icon, color }) => <Card key={label}><Icon className={color} /><p className="mt-5 text-sm text-muted">{label}</p><strong className="mt-1 block text-2xl font-black">{money(value)}</strong></Card>)}</section><Card><h2 className="text-lg font-black">Расшифровка</h2><dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[["Заказов", finance.orders.toString()], ["Не приехали", finance.no_shows.toString()], ["Работы", money(finance.labor_revenue)], ["Продажа запчастей", money(finance.parts_revenue)], ["Закупка запчастей", money(finance.parts_cost)], ["Прибыль по запчастям", money(finance.parts_profit)]].map(([label,value]) => <div key={label} className="rounded-xl bg-panel-soft p-4"><dt className="text-sm text-muted">{label}</dt><dd className="mt-1 text-xl font-black">{value}</dd></div>)}</dl></Card></div>;
}
