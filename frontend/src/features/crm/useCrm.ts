import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { CRM_KEY } from "../../lib/query";

export function useCrm() {
  return useQuery({ queryKey: CRM_KEY, queryFn: api.crm });
}
