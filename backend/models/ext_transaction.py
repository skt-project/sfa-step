"""
Pydantic models for external distributor transactions.

Deliberately NOT reusing models/visit.py: these describe a different source with
different fields, and coupling them would let an SFA schema change silently alter
the external contract (and vice versa). See docs/current/17.
"""
from pydantic import BaseModel


class ExtTransactionItem(BaseModel):
    ext_visit_item_id: str
    sku_id: str | None = None
    sku_name: str | None = None
    brand: str | None = None
    category: str | None = None
    qty: float | None = None
    stp: float | None = None
    demand: float | None = None
    line_value: float | None = None


class ExtTransaction(BaseModel):
    ext_visit_id: str
    visit_date: str | None = None
    source_username: str | None = None
    salesman_sk: str | None = None
    salesman_name: str | None = None
    source_store_id: str | None = None
    outlet_sk: str | None = None
    store_name: str | None = None
    distributor_code: str | None = None
    brand_group: str | None = None
    visit_status: str | None = None
    effective_call: str | None = None
    source_visit_type: str | None = None
    notes: str | None = None
    duration_minutes: int | None = None
    checkin_time: str | None = None
    checkout_time: str | None = None
    item_count: int = 0
    computed_qty: float | None = None
    computed_value: float | None = None
    source_total_demand: float | None = None
    total_mismatch: bool = False
    synced_at: str | None = None


class ExtTransactionDetail(ExtTransaction):
    items: list[ExtTransactionItem] = []


class ExtTransactionPagination(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool


class ExtTransactionSummary(BaseModel):
    transactions: int = 0
    total_quantity: float = 0
    total_value: float = 0
    unique_stores: int = 0
    unique_products: int = 0
    unmapped_stores: int = 0


class ExtTransactionListResponse(BaseModel):
    data: list[ExtTransaction] = []
    pagination: ExtTransactionPagination
    summary: ExtTransactionSummary
    # False when the read model is missing or BigQuery is unreachable — the UI
    # shows "source temporarily unavailable" instead of an empty-results message.
    source_available: bool = True


class ExtSalesmanOption(BaseModel):
    salesman_sk: str | None = None
    source_username: str | None = None
    salesman_name: str | None = None
    transactions: int = 0


class ExtSyncRun(BaseModel):
    batch_id: str
    started_at: str | None = None
    finished_at: str | None = None
    status: str | None = None
    triggered_by: str | None = None
    visits_read: int | None = None
    items_read: int | None = None
    visits_written: int | None = None
    items_written: int | None = None
    invalid_visits: int | None = None
    duplicate_visits: int | None = None
    orphan_items: int | None = None
    unmapped_stores: int | None = None
    unmapped_salesmen: int | None = None
    total_mismatches: int | None = None
    error: str | None = None
