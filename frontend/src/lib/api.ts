import { z } from "zod";
import type { AiUsageSummary } from "./types";
import type { Account, AppointmentInput, CarInput, CrmData, CustomerInput, Dashboard, Diagnostic, DiagnosticItem, DiagnosticItemInput, DiagnosticPhoto, DiagnosticSummary, Order, OrderInput, Organization, PartsCatalogResult, PartsCatalogStatus, ProfitLigaOrdersResult, ReceiptUploadResult, RosskoOrdersResult, SearchResults, StaffMember, StaffRole, SupplierOffer, TrashData, TrashItem, VehicleRecognition } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";
let accessToken: string | null = null;
let refreshPromise: Promise<string | null> | null = null;

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

const errorSchema = z.object({ detail: z.string().optional() });

type TokenResponse = { access_token: string; token_type: "bearer"; expires_in: number };

async function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_BASE}/api/refresh`, {
      method: "POST", credentials: "same-origin",
    }).then(async (response) => {
      if (!response.ok) return null;
      const value = await response.json() as TokenResponse;
      accessToken = value.access_token;
      return accessToken;
    }).finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

async function authenticatedFetch(path: string, init?: RequestInit, retry = true): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  let response = await fetch(`${API_BASE}${path}`, { credentials: "same-origin", ...init, headers });
  if (response.status === 401 && retry && path !== "/api/login" && path !== "/api/refresh") {
    const refreshed = await refreshAccessToken();
    if (refreshed) response = await authenticatedFetch(path, init, false);
  }
  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await authenticatedFetch(path, { ...init, signal: controller.signal });
    if (!response.ok) {
      const parsed = errorSchema.safeParse(await response.json().catch(() => ({})));
      throw new ApiError(response.status, parsed.success && parsed.data.detail ? parsed.data.detail : "Не удалось выполнить запрос");
    }
    const value = await response.json() as T;
    if (value && typeof value === "object" && "access_token" in value) {
      accessToken = String((value as Record<string, unknown>).access_token);
    }
    return value;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") throw new ApiError(408, "Сервер отвечает слишком долго");
    throw new ApiError(0, "Нет связи с сервером");
  } finally { window.clearTimeout(timeout); }
}

const json = (value: unknown): RequestInit => ({ body: JSON.stringify(value) });
export const api = {
  login: (username: string, password: string) => request<{ status: string } & TokenResponse>("/api/login", { method: "POST", ...json({ username, password }) }),
  logout: async () => { const result = await request<{ status: string }>("/api/logout", { method: "POST" }); accessToken = null; return result; },
  account: () => request<Account>("/api/account"),
  staff: () => request<StaffMember[]>("/api/settings/staff"),
  createStaff: (value: { username: string; password: string; full_name: string; role: StaffRole }) => request<StaffMember>("/api/settings/staff", { method: "POST", ...json(value) }),
  updateStaff: (id: number, value: { role?: StaffRole; active?: boolean; password?: string }) => request<StaffMember>(`/api/settings/staff/${id}`, { method: "PATCH", ...json(value) }),
  workspace: () => request<{ id: number; name: string; city: string | null }>("/api/settings/workspace"),
  updateWorkspace: (value: { name: string; city: string }) => request<{ id: number; name: string; city: string | null }>("/api/settings/workspace", { method: "PUT", ...json(value) }),
  changePassword: (current_password: string, new_password: string) => request<{ status: string }>("/api/settings/password", { method: "PUT", ...json({ current_password, new_password }) }),
  organizations: () => request<Organization[]>("/api/platform/organizations"),
  createOrganization: (value: { name: string; city: string; owner_name: string; username: string; password: string; demo: boolean }) => request<Organization>("/api/platform/organizations", { method: "POST", ...json(value) }),
  updateOrganizationAccess: (id: number, action: "block" | "activate" | "demo") => request<Organization>(`/api/platform/organizations/${id}/access`, { method: "POST", ...json({ action }) }),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  aiUsage: (period: number) => request<AiUsageSummary>(`/api/finance/ai-usage?period=${period}`),
  crm: () => request<CrmData>("/api/crm"),
  search: (query: string) => request<SearchResults>(`/api/search?q=${encodeURIComponent(query)}`),
  trash: () => request<TrashData>("/api/trash"),
  restoreTrashItem: (kind: TrashItem["kind"], id: number) => request<{ status: string }>(`/api/trash/${kind}/${id}/restore`, { method: "POST" }),
  diagnostics: (carId?: number) => request<DiagnosticSummary[]>(`/api/diagnostics${carId ? `?car_id=${carId}` : ""}`),
  diagnostic: (id: number) => request<Diagnostic>(`/api/diagnostics/${id}`),
  diagnosticPdf: async (id: number) => {
    const response = await authenticatedFetch(`/api/diagnostics/${id}/pdf`);
    if (!response.ok) throw new ApiError(response.status, "Не удалось сформировать PDF");
    return response.blob();
  },
  startDiagnostic: (carId: number, serviceOrderId?: number) => request<Diagnostic>("/api/diagnostics/start", { method: "POST", ...json({ car_id: carId, service_order_id: serviceOrderId ?? null }) }),
  updateDiagnostic: (id: number, value: { mileage: number | null; notes: string | null; status: "draft" | "completed" }) => request<Diagnostic>(`/api/diagnostics/${id}`, { method: "PUT", ...json(value) }),
  createOrderFromDiagnostic: (id: number) => request<Order & { created_from_diagnostic: boolean }>(`/api/diagnostics/${id}/create-order`, { method: "POST" }),
  deleteDiagnostic: (id: number) => request<{ status: string }>(`/api/diagnostics/${id}`, { method: "DELETE" }),
  updateDiagnosticItem: (id: number, itemKey: string, value: DiagnosticItemInput) => request<DiagnosticItem>(`/api/diagnostics/${id}/items/${encodeURIComponent(itemKey)}`, { method: "PUT", ...json(value) }),
  uploadDiagnosticPhoto: (id: number, file: File) => request<DiagnosticPhoto>(`/api/diagnostics/${id}/photos`, { method: "POST", body: file, headers: { "Content-Type": file.type } }),
  recognizeVehicleImage: (file: File) => request<VehicleRecognition>("/api/vehicle-recognition/image", { method: "POST", body: file, headers: { "Content-Type": file.type } }),
  recognizeVehicleVin: (vin: string) => request<VehicleRecognition>("/api/vehicle-recognition/vin", { method: "POST", ...json({ vin }) }),
  partsCatalogStatus: () => request<PartsCatalogStatus>("/api/parts-catalog/status"),
  searchParts: (query: string, markupPercent: number, supplier?: "rossko" | "profit_liga") => request<PartsCatalogResult>(`/api/parts-catalog/search?q=${encodeURIComponent(query)}&markup_percent=${markupPercent}${supplier ? `&supplier=${supplier}` : ""}`),
  addPartToOrder: (offer: SupplierOffer, orderId: number, quantity: number) => request("/api/parts-catalog/add-to-order", { method: "POST", ...json({ order_id: orderId, name: `${offer.brand} ${offer.name}`.trim(), article: offer.article, quantity, purchase_price: offer.purchase_price, markup_percent: offer.markup_percent }) }),
  rosskoOrders: (orderId: number) => request<RosskoOrdersResult>(`/api/parts-catalog/rossko-orders?order_id=${orderId}`),
  importRosskoOrder: (orderId: number, rosskoOrderId: number, markupPercent: number, partArticles?: string[]) => request<{ items_count: number; purchase_cost: number; selling_price: number }>("/api/parts-catalog/import-rossko-order", { method: "POST", ...json({ order_id: orderId, rossko_order_id: rosskoOrderId, markup_percent: markupPercent, part_articles: partArticles }) }),
  profitLigaOrders: (orderId: number) => request<ProfitLigaOrdersResult>(`/api/parts-catalog/profit-orders?order_id=${orderId}`),
  importProfitLigaOrder: (orderId: number, profitOrderId: string, markupPercent: number, partArticles?: string[]) => request<{ items_count: number; purchase_cost: number; selling_price: number }>("/api/parts-catalog/import-profit-order", { method: "POST", ...json({ order_id: orderId, profit_order_id: profitOrderId, markup_percent: markupPercent, part_articles: partArticles }) }),
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
