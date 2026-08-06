import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 20_000, retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2 },
    mutations: { retry: false },
  },
});

export const CRM_KEY = ["crm"] as const;
export const DASHBOARD_KEY = ["dashboard"] as const;
export async function refreshCrm() {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: CRM_KEY }),
    queryClient.invalidateQueries({ queryKey: DASHBOARD_KEY }),
  ]);
}
