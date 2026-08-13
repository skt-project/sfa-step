import { api } from "./client";
import type {
  ExtSalesmanOption,
  ExtTransactionDetail,
  ExtTransactionListResponse,
} from "@/types";

// External (non-SFA) transaction source. These endpoints read a separate model —
// they never touch /visit, and nothing here can modify SFA transaction data.

export interface ExtTransactionFilters {
  from_date?: string;
  to_date?: string;
  salesman_sk?: string;
  store?: string;
  search?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export const listExtTransactions = (params: ExtTransactionFilters) =>
  api.get<ExtTransactionListResponse>("/ext-transaction", { params }).then((r) => r.data);

export const getExtTransaction = (id: string) =>
  api.get<ExtTransactionDetail>(`/ext-transaction/${encodeURIComponent(id)}`).then((r) => r.data);

export const listExtSalesmen = (params: { from_date?: string; to_date?: string }) =>
  api.get<ExtSalesmanOption[]>("/ext-transaction/salesmen", { params }).then((r) => r.data);

export const triggerExtSync = () =>
  api.post("/ext-transaction/sync").then((r) => r.data);
