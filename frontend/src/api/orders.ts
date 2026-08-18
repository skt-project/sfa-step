import { api } from "./client";
import type { OrderItemRow, OrderListResponse, OrderRow } from "@/types";

// Unified multi-source order list. SFA and spreadsheet orders arrive already
// merged, scoped and labelled by the backend.

export interface OrderFilters {
  from_date?: string;
  to_date?: string;
  source?: string;          // ALL | SFA | SPREADSHEET
  status?: string;
  store?: string;
  sku?: string;
  order_number?: string;
  search?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export const listOrders = (params: OrderFilters) =>
  api.get<OrderListResponse>("/orders", { params }).then((r) => r.data);

export const getOrderDetail = (source: string, order_id: string) =>
  api
    .get<{ order: OrderRow | null; items: OrderItemRow[] }>("/orders/detail", {
      params: { source, order_id },
    })
    .then((r) => r.data);

/** Download the current view as .xlsx. Sends the SAME filters as the list, so
 *  the workbook always matches what is on screen. */
export const exportOrders = async (params: OrderFilters): Promise<void> => {
  const res = await api.get("/orders/export", { params, responseType: "blob" });
  const disposition = String(res.headers["content-disposition"] ?? "");
  const match = disposition.match(/filename="?([^"]+)"?/);
  const url = window.URL.createObjectURL(new Blob([res.data]));
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] ?? "VisitOrder.xlsx";
  a.click();
  window.URL.revokeObjectURL(url);
};
