import { z } from "zod";
import type { AppointmentInput, CarInput, CrmData, CustomerInput, Dashboard, OrderInput, SearchResults } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

const errorSchema = z.object({ detail: z.string().optional() });

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      credentials: "same-origin",
      ...init,
      headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      const parsed = errorSchema.safeParse(await response.json().catch(() => ({})));
      throw new ApiError(response.status, parsed.success && parsed.data.detail ? parsed.data.detail : "Не удалось выполнить запрос");
    }
    return await response.json() as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") throw new ApiError(408, "Сервер отвечает слишком долго");
    throw new ApiError(0, "Нет связи с сервером");
  } finally { window.clearTimeout(timeout); }
}

const json = (value: unknown): RequestInit => ({ body: JSON.stringify(value) });
export const api = {
  login: (username: string, password: string) => request<{ status: string }>("/api/login", { method: "POST", ...json({ username, password }) }),
  logout: () => request<{ status: string }>("/api/logout", { method: "POST" }),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  crm: () => request<CrmData>("/api/crm"),
  search: (query: string) => request<SearchResults>(`/api/search?q=${encodeURIComponent(query)}`),
  saveCustomer: (data: CustomerInput, id?: number) => request(`/api/customers${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", ...json(data) }),
  saveCar: (data: CarInput, id?: number) => request(`/api/cars${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", ...json(data) }),
  saveAppointment: (data: AppointmentInput, id?: number) => request(`/api/appointments${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", ...json(data) }),
  appointmentAction: (id: number, action: "arrived" | "no_show") => request(`/api/appointments/${id}/action`, { method: "POST", ...json({ action }) }),
  saveOrder: (data: OrderInput, id?: number) => request(`/api/orders${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", ...json(data) }),
  orderStatus: (id: number, action: "ready" | "in_progress" | "completed") => request(`/api/orders/${id}/status`, { method: "POST", ...json({ action }) }),
};
