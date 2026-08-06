export type Customer = { id: number; user_id: number; full_name: string; phone: string | null };
export type Car = {
  id: number; user_id: number; customer_id: number | null; brand: string; model: string;
  year: number | null; plate_number: string | null; vin: string | null; mileage: number | null;
  next_service_date: string | null; next_service_mileage: number | null;
};
export type Appointment = {
  id: number; car_id: number; service_order_id: number | null; description: string;
  starts_at: string; status: string; brand: string; model: string; plate_number: string | null;
  customer_name: string | null; customer_phone: string | null; agreed_amount: number | null;
  is_flexible: boolean; parts_source: string | null;
};
export type Order = {
  id: number; car_id: number; description: string; labor_revenue: number; parts_cost: number;
  parts_revenue: number; parts_profit: number; status: string; created_at: string; brand: string;
  model: string; plate_number: string | null; vin: string | null; mileage: number | null;
  customer_name: string | null; concern: string | null; agreed_amount: number | null;
  recommendations: string | null; completed_at: string | null; archived_at: string | null;
  parts_source: string | null; mileage_at_visit: number | null; profit: number;
};
export type Finance = {
  orders: number; no_shows: number; labor_revenue: number; parts_revenue: number;
  parts_cost: number; parts_profit: number; today_profit: number; revenue: number; profit: number;
};
export type CrmData = { customers: Customer[]; cars: Car[]; appointments: Appointment[]; orders: Order[]; finance: Finance };
export type Dashboard = { today_profit: number; active_orders: number; upcoming_appointments: number; orders: Order[]; appointments: Appointment[] };
export type SearchResults = { customers: Customer[]; cars: Car[]; orders: Order[]; appointments: Appointment[] };

export type CustomerInput = { full_name: string; phone: string | null };
export type CarInput = { customer_id: number | null; brand: string; model: string; year: number | null; plate_number: string | null; vin: string | null; mileage: number | null };
export type AppointmentInput = { car_id: number; description: string; starts_at: string; agreed_amount: number | null; is_flexible: boolean; parts_source: string | null };
export type OrderInput = { car_id: number; description: string; labor_revenue: number; parts_cost: number; parts_revenue: number; parts_profit: number; concern: string | null; agreed_amount: number | null; recommendations: string | null; parts_source: string | null };
