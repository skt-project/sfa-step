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

/** Distributor Admin invoice adjustment for a Spreadsheet order — the same
 *  capability SFA orders already have. SFA orders keep using their own existing
 *  updateAdjustment() in api/visit.ts; this is Spreadsheet-only. */
export const updateOrderAdjustment = (
  order_id: string,
  adjustment_amount: number,
  adjustment_note: string | null,
) =>
  api
    .put<{ order: OrderRow }>("/orders/adjustment", {
      source: "SPREADSHEET", order_id, adjustment_amount, adjustment_note,
    })
    .then((r) => r.data);

async function downloadBlob(url: string, params: object, fallbackName: string) {
  const res = await api.get(url, { params, responseType: "blob" });
  const disposition = String(res.headers["content-disposition"] ?? "");
  const match = disposition.match(/filename="?([^"]+)"?/);
  const blobUrl = window.URL.createObjectURL(new Blob([res.data]));
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = match?.[1] ?? fallbackName;
  a.click();
  window.URL.revokeObjectURL(blobUrl);
}

/** Download the current view as .xlsx. Sends the SAME filters as the list, so
 *  the workbook always matches what is on screen. */
export const exportOrders = (params: OrderFilters): Promise<void> =>
  downloadBlob("/orders/export", params, "VisitOrder.xlsx");

/** Download a single order (both sheets: summary + items) as .xlsx. Works for
 *  either source — same endpoint, same shape as the bulk export. */
export const exportSingleOrder = (source: string, orderId: string): Promise<void> =>
  downloadBlob(`/orders/export/${encodeURIComponent(source)}/${encodeURIComponent(orderId)}`, {}, `Order_${orderId}.xlsx`);
