"""
Normalized multi-source order model.

One shape for orders regardless of origin. `source` is mandatory on every row —
a caller must always be able to tell where a record came from without opening
the detail view.

Only fields that genuinely exist in a source are populated; anything a source
does not carry stays None rather than being invented.
"""
from pydantic import BaseModel


class OrderRow(BaseModel):
    # Provenance — always present
    source: str                      # "SFA" | "SPREADSHEET"
    source_label: str                # human-readable, shown in the table + export

    order_id: str                    # opaque id used to open the detail view
    order_number: str | None = None  # business-facing identifier
    order_date: str | None = None    # YYYY-MM-DD (calendar date, never tz-shifted)

    store_id: str | None = None
    store_name: str | None = None
    distributor_code: str | None = None
    distributor_name: str | None = None
    salesman_name: str | None = None

    item_count: int = 0
    product_summary: str | None = None   # single product name, or "N produk"
    quantity: float | None = None
    order_value: float | None = None
    status: str | None = None


class OrderItemRow(BaseModel):
    """Line item — used by the detail view and the Excel "Order Details" sheet."""
    source: str
    order_id: str
    order_number: str | None = None
    order_date: str | None = None
    store_id: str | None = None
    store_name: str | None = None
    sku: str | None = None
    product_name: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    line_value: float | None = None
    status: str | None = None


class SourceStatus(BaseModel):
    """Per-source health, so one source failing is visible without hiding the rest."""
    source: str
    label: str
    ok: bool
    count: int = 0
    error: str | None = None


class OrderSummary(BaseModel):
    total_orders: int = 0
    pending_orders: int = 0
    completed_orders: int = 0
    total_quantity: float = 0
    total_value: float = 0


class OrderPagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool


class OrderListResponse(BaseModel):
    data: list[OrderRow] = []
    pagination: OrderPagination
    summary: OrderSummary
    sources: list[SourceStatus] = []
    truncated: bool = False          # merge cap hit; see routers/orders.MAX_MERGE
