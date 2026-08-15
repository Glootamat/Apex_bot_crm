import { useSyncExternalStore } from "react";

export type ModuleKey = "calendar" | "orders" | "diagnostics" | "customers" | "cars" | "laborStandards" | "finance" | "trash";
export type AppSettings = {
  workspaceName: string; city: string; modules: Record<ModuleKey, boolean>;
  laborHourRate: number;
  compactMode: boolean; reduceMotion: boolean; desktopNotifications: boolean;
  appointmentReminders: boolean; orderStatusNotifications: boolean; dailySummary: boolean;
  autoLockMinutes: number;
};
export const defaultSettings: AppSettings = {
  workspaceName: "APEX AUTO", city: "Москва",
  modules: { calendar: false, orders: false, diagnostics: false, customers: true, cars: true, laborStandards: false, finance: false, trash: true },
  laborHourRate: 2000,
  compactMode: false, reduceMotion: false, desktopNotifications: false,
  appointmentReminders: true, orderStatusNotifications: true, dailySummary: false, autoLockMinutes: 30,
};
const STORAGE_KEY = "apex-crm-settings-v1";
let cached: AppSettings | null = null;
function readSettings(): AppSettings {
  if (cached) return cached;
  try { const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<AppSettings>; cached = { ...defaultSettings, ...saved, modules: { ...defaultSettings.modules, ...saved.modules } }; }
  catch { cached = defaultSettings; }
  return cached;
}
const listeners = new Set<() => void>();
function subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener); }
export function saveSettings(value: AppSettings) { cached = value; localStorage.setItem(STORAGE_KEY, JSON.stringify(value)); listeners.forEach((listener) => listener()); }
export function useAppSettings() { return useSyncExternalStore(subscribe, readSettings, () => defaultSettings); }
