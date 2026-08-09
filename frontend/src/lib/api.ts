import { z } from "zod";
import type { AppointmentInput, CarInput, CrmData, CustomerInput, Dashboard, Diagnostic, DiagnosticItem, DiagnosticItemInput, DiagnosticPhoto, DiagnosticSummary, OrderInput, PartsCatalogResult, PartsCatalogStatus, ReceiptUploadResult, SearchResults, SupplierOffer, TrashData, TrashItem, VehicleRecognition } from "./types";

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
  trash: () => request<TrashData>("/api/trash"),
  restoreTrashItem: (kind: TrashItem["kind"], id: number) => request<{ status: string }>(`/api/trash/${kind}/${id}/restore`, { method: "POST" }),
  diagnostics: (carId?: number) => request<DiagnosticSummary[]>(`/api/diagnostics${carId ? `?car_id=${carId}` : ""}`),
  diagnostic: (id: number) => request<Diagnostic>(`/api/diagnostics/${id}`),
  diagnosticPdf: async (id: number) => {
    const response = await fetch(`${API_BASE}/api/diagnostics/${id}/pdf`, { credentials: "same-origin" });
    if (!response.ok) throw new ApiError(response.status, "Не удалось сформировать PDF");
    return response.blob();
  },
  startDiagnostic: (carId: number, serviceOrderId?: number) => request<Diagnostic>("/api/diagnostics/start", { method: "POST", ...json({ car_id: carId, service_order_id: serviceOrderId ?? null }) }),
  updateDiagnostic: (id: number, value: { mileage: number | null; notes: string | null; status: "draft" | "completed" }) => request<Diagnostic>(`/api/diagnostics/${id}`, { method: "PUT", ...json(value) }),
  deleteDiagnostic: (id: number) => request<{ status: string }>(`/api/diagnostics/${id}`, { method: "DELETE" }),
  updateDiagnosticItem: (id: number, itemKey: string, value: DiagnosticItemInput) => request<DiagnosticItem>(`/api/diagnostics/${id}/items/${encodeURIComponent(itemKey)}`, { method: "PUT", ...json(value) }),
  uploadDiagnosticPhoto: (id: number, file: File) => request<DiagnosticPhoto>(`/api/diagnostics/${id}/photos`, { method: "POST", body: file, headers: { "Content-Type": file.type } }),
  recognizeVehicleImage: (file: File) => request<VehicleRecognition>("/api/vehicle-recognition/image", { method: "POST", body: file, headers: { "Content-Type": file.type } }),
  recognizeVehicleVin: (vin: string) => request<VehicleRecognition>("/api/vehicle-recognition/vin", { method: "POST", ...json({ vin }) }),
  partsCatalogStatus: () => request<PartsCatalogStatus>("/api/parts-catalog/status"),
  searchParts: (query: string, markupPercent: number) => request<PartsCatalogResult>(`/api/parts-catalog/search?q=${encodeURIComponent(query)}&markup_percent=${markupPercent}`),
  addPartToOrder: (offer: SupplierOffer, orderId: number, quantity: number) => request("/api/parts-catalog/add-to-order", { method: "POST", ...json({ order_id: orderId, name: `${offer.brand} ${offer.name}`.trim(), article: offer.article, quantity, purchase_price: offer.purchase_price, markup_percent: offer.markup_percent }) }),
  saveCustomer: (data: CustomerInput, id?: number) => request(`/api/customers${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", ...json(data) }),
  deleteCustomer: (id: number) => request<{ status: string }>(`/api/customers/${id}`, { method: "DELETE" }),
  saveCar: (data: CarInput, id?: number) => request(`/api/cars${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", ...json(data) }),
  deleteCar: (id: number) => request<{ status: string }>(`/api/cars/${id}`, { method: "DELETE" }),
  saveAppointment: (data: AppointmentInput, id?: number) => request(`/api/appointments${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", ...json(data) }),
  deleteAppointment: (id: number) => request<{ status: string }>(`/api/appointments/${id}`, { method: "DELETE" }),
  appointmentAction: (id: number, action: "arrived" | "no_show") => request(`/api/appointments/${id}/action`, { method: "POST", ...json({ action }) }),
  saveOrder: (data: OrderInput, id?: number) => request(`/api/orders${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", ...json(data) }),
  deleteOrder: (id: number) => request<{ status: string }>(`/api/orders/${id}`, { method: "DELETE" }),
  orderStatus: (id: number, action: "ready" | "in_progress" | "completed") => request(`/api/orders/${id}/status`, { method: "POST", ...json({ action }) }),
  uploadOrderPhoto: (id: number, file: File, photoType: "work" | "receipt") => request<ReceiptUploadResult>(`/api/orders/${id}/photos?photo_type=${photoType}`, { method: "POST", body: file, headers: { "Content-Type": file.type } }),
};
