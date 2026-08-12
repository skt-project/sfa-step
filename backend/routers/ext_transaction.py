"""
External Distributor Transactions — read-only history from an external source.

GET  /ext-transaction              — paginated transaction list + summary
GET  /ext-transaction/summary      — summary only (same filters)
GET  /ext-transaction/salesmen     — salesman options inside the caller's scope
GET  /ext-transaction/sync/status  — recent sync runs (ho_admin)
POST /ext-transaction/sync         — trigger a sync (ho_admin)
GET  /ext-transaction/{id}         — one transaction + its items

SOURCE SEPARATION: every query here reads ext_visit / ext_visit_item only. No
statement in this module references step_visit, step_visit_item, or any other SFA
transaction table, and nothing here writes to the SFA pipeline.

AUTHORIZATION: scoping is server-side and fails CLOSED. A `dm` is pinned to their
own distributor_code regardless of any query parameter; a `dm` with no
distributor_code sees nothing rather than everything. Client-supplied salesman /
store filters narrow the scope, they can never widen it.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from config import settings
from dependencies import require_auth, require_role
from models.auth import UserContext
from models.ext_transaction import (
    ExtSalesmanOption,
    ExtSyncRun,
    ExtTransaction,
    ExtTransactionDetail,
    ExtTransactionItem,
    ExtTransactionListResponse,
    ExtTransactionPagination,
    ExtTransactionSummary,
)
from services.audit import log_event
from services.bq import BQClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ext-transaction", tags=["ext_transaction"])

# Roles allowed anywhere near this feature. Distributors are the audience;
# ho_admin gets the unscoped view for support and data-quality work.
_ALLOWED_ROLES = ("dm", "ho_admin")

_SORTABLE = {
    "visit_date": "v.visit_date",
    "value": "v.computed_value",
    "quantity": "v.computed_qty",
    "items": "v.item_count",
    "store": "v.store_name",
    "salesman": "v.salesman_name",
}

_LIST_COLS = """
    v.ext_visit_id, v.visit_date, v.source_username, v.salesman_sk, v.salesman_name,
    v.source_store_id, v.outlet_sk, v.store_name, v.distributor_code, v.brand_group,
    v.visit_status, v.effective_call, v.source_visit_type, v.notes, v.duration_minutes,
    v.checkin_time, v.checkout_time, v.item_count, v.computed_qty, v.computed_value,
    v.source_total_demand, v.total_mismatch, v.synced_at
"""


def _tbl(name: str) -> str:
    return f"`{settings.bq_project}.{settings.bq_dataset}.{name}`"


def distributor_scope(user: UserContext) -> tuple[str, list]:
    """SQL predicate restricting rows to what `user` may see. FAILS CLOSED.

    ho_admin  → unrestricted (support/data-quality).
    dm        → pinned to their own distributor_code. Transactions whose store did
                not resolve to a STEP outlet have distributor_code NULL and are
                therefore invisible to every dm — deliberately, since an unmapped
                store cannot be proven to belong to them.
    anything else → nothing (defence in depth; require_role already blocks them).
    """
    if user.role == "ho_admin":
        return "", []
    if user.role == "dm":
        if not user.distributor_code:
            return "AND 1=0", []
        return "AND v.distributor_code = @scope_dist", [
            BQClient.p("scope_dist", "STRING", user.distributor_code)
        ]
    return "AND 1=0", []


def _filters(
    user: UserContext,
    from_date: str | None,
    to_date: str | None,
    salesman_sk: str | None,
    store: str | None,
    search: str | None,
) -> tuple[str, list]:
    """Build the shared WHERE fragment. Scope first, user filters can only narrow."""
    clause, params = distributor_scope(user)
    conditions = [clause] if clause else []

    if from_date:
        conditions.append("AND v.visit_date >= @from_date")
        params.append(BQClient.p("from_date", "DATE", from_date))
    if to_date:
        conditions.append("AND v.visit_date <= @to_date")
        params.append(BQClient.p("to_date", "DATE", to_date))
    if salesman_sk:
        # Narrows within the scope; the scope clause above still applies, so a
        # forged salesman_sk from another distributor simply matches no rows.
        conditions.append("AND (v.salesman_sk = @sm OR v.source_username = @sm)")
        params.append(BQClient.p("sm", "STRING", salesman_sk))
    if store:
        conditions.append(
            "AND (LOWER(v.store_name) LIKE @store OR LOWER(v.source_store_id) LIKE @store)"
        )
        params.append(BQClient.p("store", "STRING", f"%{store.lower()}%"))
    if search:
        # Transaction id / store / salesman, plus product + SKU via the item table.
        conditions.append(f"""
        AND (
            LOWER(v.ext_visit_id) LIKE @q
            OR LOWER(v.store_name) LIKE @q
            OR LOWER(v.source_store_id) LIKE @q
            OR LOWER(v.salesman_name) LIKE @q
            OR LOWER(v.source_username) LIKE @q
            OR EXISTS (
                SELECT 1 FROM {_tbl('ext_visit_item')} i
                WHERE i.ext_visit_id = v.ext_visit_id
                  AND (LOWER(i.sku_id) LIKE @q OR LOWER(i.sku_name) LIKE @q)
            )
        )""")
        params.append(BQClient.p("q", "STRING", f"%{search.lower()}%"))

    return " ".join(conditions), params


def _empty_response(page: int, page_size: int, available: bool) -> ExtTransactionListResponse:
    return ExtTransactionListResponse(
        data=[],
        pagination=ExtTransactionPagination(
            page=page, page_size=page_size, total=0, total_pages=0, has_next=False
        ),
        summary=ExtTransactionSummary(),
        source_available=available,
    )


def _is_missing_source(exc: Exception) -> bool:
    """The read model has not been created yet (migration 007 not run), or the
    dataset is unreachable. Treated as 'source unavailable', not a 500."""
    text = str(exc).lower()
    return "not found" in text or "was not found" in text or "does not have" in text


def _iso(v) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def _row_to_transaction(r: dict) -> ExtTransaction:
    return ExtTransaction(
        ext_visit_id=r["ext_visit_id"],
        visit_date=_iso(r.get("visit_date")),
        source_username=r.get("source_username"),
        salesman_sk=r.get("salesman_sk"),
        salesman_name=r.get("salesman_name"),
        source_store_id=r.get("source_store_id"),
        outlet_sk=r.get("outlet_sk"),
        store_name=r.get("store_name"),
        distributor_code=r.get("distributor_code"),
        brand_group=r.get("brand_group"),
        visit_status=r.get("visit_status"),
        effective_call=r.get("effective_call"),
        source_visit_type=r.get("source_visit_type"),
        notes=r.get("notes"),
        duration_minutes=r.get("duration_minutes"),
        checkin_time=_iso(r.get("checkin_time")),
        checkout_time=_iso(r.get("checkout_time")),
        item_count=int(r.get("item_count") or 0),
        computed_qty=r.get("computed_qty"),
        computed_value=r.get("computed_value"),
        source_total_demand=r.get("source_total_demand"),
        total_mismatch=bool(r.get("total_mismatch")),
        synced_at=_iso(r.get("synced_at")),
    )


def _summary(bq, where: str, params: list) -> ExtTransactionSummary:
    """Summary over the FULL filtered set, not just the current page.

    Aggregates read the header's precomputed columns, so no item join is needed
    and a multi-item transaction can never be counted twice. unique_products is
    the one figure that must touch the item table.
    """
    row = bq.query_one(f"""
        SELECT COUNT(*) AS transactions,
               SUM(v.computed_qty) AS total_quantity,
               SUM(v.computed_value) AS total_value,
               COUNT(DISTINCT COALESCE(v.outlet_sk, v.source_store_id)) AS unique_stores,
               COUNT(DISTINCT IF(v.outlet_sk IS NULL, v.source_store_id, NULL)) AS unmapped_stores
        FROM {_tbl('ext_visit')} v
        WHERE TRUE {where}
    """, params) or {}

    prod = bq.query_one(f"""
        SELECT COUNT(DISTINCT i.sku_id) AS unique_products
        FROM {_tbl('ext_visit')} v
        JOIN {_tbl('ext_visit_item')} i ON i.ext_visit_id = v.ext_visit_id
        WHERE TRUE {where}
    """, params) or {}

    return ExtTransactionSummary(
        transactions=int(row.get("transactions") or 0),
        total_quantity=float(row.get("total_quantity") or 0),
        total_value=float(row.get("total_value") or 0),
        unique_stores=int(row.get("unique_stores") or 0),
        unmapped_stores=int(row.get("unmapped_stores") or 0),
        unique_products=int(prod.get("unique_products") or 0),
    )


# ---------------------------------------------------------------------------
# GET /ext-transaction  — list
# ---------------------------------------------------------------------------
@router.get("", response_model=ExtTransactionListResponse)
def list_transactions(
    from_date: str | None = Query(None, description="Inclusive lower bound, YYYY-MM-DD"),
    to_date: str | None = Query(None, description="Inclusive upper bound, YYYY-MM-DD"),
    salesman_sk: str | None = Query(None, description="salesman_sk or the source username"),
    store: str | None = Query(None, description="Partial store name or source store id"),
    search: str | None = Query(None, description="Transaction id, store, salesman, SKU or product"),
    sort_by: str = Query("visit_date"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: UserContext = Depends(require_role(*_ALLOWED_ROLES)),
):
    bq = BQClient.get()
    where, params = _filters(current_user, from_date, to_date, salesman_sk, store, search)

    order_col = _SORTABLE.get(sort_by, _SORTABLE["visit_date"])
    direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"
    offset = (page - 1) * page_size

    try:
        summary = _summary(bq, where, params)
        rows = bq.query(f"""
            SELECT {_LIST_COLS}
            FROM {_tbl('ext_visit')} v
            WHERE TRUE {where}
            ORDER BY {order_col} {direction}, v.ext_visit_id
            LIMIT @lim OFFSET @off
        """, params + [
            BQClient.p("lim", "INT64", page_size),
            BQClient.p("off", "INT64", offset),
        ])
    except Exception as exc:
        if _is_missing_source(exc):
            logger.warning("ext_tx: read model unavailable — %s", type(exc).__name__)
            return _empty_response(page, page_size, available=False)
        logger.exception("ext_tx: list query failed")
        raise HTTPException(status_code=503, detail="Transaction source is temporarily unavailable.")

    total = summary.transactions
    total_pages = (total + page_size - 1) // page_size
    return ExtTransactionListResponse(
        data=[_row_to_transaction(r) for r in rows],
        pagination=ExtTransactionPagination(
            page=page, page_size=page_size, total=total,
            total_pages=total_pages, has_next=(offset + page_size) < total,
        ),
        summary=summary,
    )


# ---------------------------------------------------------------------------
# GET /ext-transaction/summary
# ---------------------------------------------------------------------------
@router.get("/summary", response_model=ExtTransactionSummary)
def transaction_summary(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    salesman_sk: str | None = Query(None),
    store: str | None = Query(None),
    search: str | None = Query(None),
    current_user: UserContext = Depends(require_role(*_ALLOWED_ROLES)),
):
    bq = BQClient.get()
    where, params = _filters(current_user, from_date, to_date, salesman_sk, store, search)
    try:
        return _summary(bq, where, params)
    except Exception as exc:
        if _is_missing_source(exc):
            return ExtTransactionSummary()
        logger.exception("ext_tx: summary query failed")
        raise HTTPException(status_code=503, detail="Transaction source is temporarily unavailable.")


# ---------------------------------------------------------------------------
# GET /ext-transaction/salesmen — filter options, already scoped
# ---------------------------------------------------------------------------
@router.get("/salesmen", response_model=list[ExtSalesmanOption])
def list_scoped_salesmen(
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    current_user: UserContext = Depends(require_role(*_ALLOWED_ROLES)),
):
    """Salesmen that actually appear in the caller's own transactions.

    Derived from the scoped transaction set rather than from the spreadsheet's
    user tab, so a distributor can never enumerate another distributor's team.
    """
    bq = BQClient.get()
    where, params = _filters(current_user, from_date, to_date, None, None, None)
    try:
        rows = bq.query(f"""
            SELECT v.salesman_sk, v.source_username,
                   COALESCE(MAX(v.salesman_name), v.source_username) AS salesman_name,
                   COUNT(*) AS transactions
            FROM {_tbl('ext_visit')} v
            WHERE TRUE {where}
            GROUP BY v.salesman_sk, v.source_username
            ORDER BY transactions DESC
            LIMIT 500
        """, params)
    except Exception as exc:
        if _is_missing_source(exc):
            return []
        logger.exception("ext_tx: salesman option query failed")
        raise HTTPException(status_code=503, detail="Transaction source is temporarily unavailable.")

    return [
        ExtSalesmanOption(
            salesman_sk=r.get("salesman_sk"),
            source_username=r.get("source_username"),
            salesman_name=r.get("salesman_name"),
            transactions=int(r.get("transactions") or 0),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Sync admin (ho_admin only)
# ---------------------------------------------------------------------------
@router.get("/sync/status", response_model=list[ExtSyncRun])
def sync_status(
    limit: int = Query(10, ge=1, le=50),
    current_user: UserContext = Depends(require_role("ho_admin")),
):
    bq = BQClient.get()
    try:
        rows = bq.query(
            f"SELECT * FROM {_tbl('ext_transaction_sync_log')} "
            "ORDER BY started_at DESC LIMIT @lim",
            [BQClient.p("lim", "INT64", limit)],
        )
    except Exception as exc:
        if _is_missing_source(exc):
            return []
        raise HTTPException(status_code=503, detail="Sync log is temporarily unavailable.")
    return [
        ExtSyncRun(
            batch_id=r.get("batch_id") or "",
            started_at=_iso(r.get("started_at")),
            finished_at=_iso(r.get("finished_at")),
            **{k: r.get(k) for k in (
                "status", "triggered_by", "visits_read", "items_read", "visits_written",
                "items_written", "invalid_visits", "duplicate_visits", "orphan_items",
                "unmapped_stores", "unmapped_salesmen", "total_mismatches", "error",
            )},
        )
        for r in rows
    ]


@router.post("/sync")
def trigger_sync(current_user: UserContext = Depends(require_role("ho_admin"))):
    """Pull the external spreadsheet into the read model. Read-only against the
    source — the sync never writes back to the spreadsheet."""
    from services.ext_transactions import run_sync

    result = run_sync(triggered_by=current_user.username)
    log_event("ext_transaction.sync", "ext_visit", result.batch_id, current_user.username,
              payload={"status": result.status, "visits": result.visits_written})
    if result.status == "FAILED":
        raise HTTPException(
            status_code=503,
            detail="Transaction source is temporarily unavailable. Please try again later.",
        )
    return result.as_dict()


# ---------------------------------------------------------------------------
# GET /ext-transaction/{ext_visit_id} — detail. MUST stay last: FastAPI matches
# routes in declaration order, so a dynamic segment defined earlier would
# swallow /summary, /salesmen and /sync.
# ---------------------------------------------------------------------------
@router.get("/{ext_visit_id}", response_model=ExtTransactionDetail)
def get_transaction(
    ext_visit_id: str,
    current_user: UserContext = Depends(require_role(*_ALLOWED_ROLES)),
):
    bq = BQClient.get()
    scope_clause, scope_params = distributor_scope(current_user)

    try:
        row = bq.query_one(f"""
            SELECT {_LIST_COLS}
            FROM {_tbl('ext_visit')} v
            WHERE v.ext_visit_id = @id {scope_clause}
        """, scope_params + [BQClient.p("id", "STRING", ext_visit_id)])
    except Exception as exc:
        if _is_missing_source(exc):
            raise HTTPException(status_code=503, detail="Transaction source is temporarily unavailable.")
        logger.exception("ext_tx: detail query failed")
        raise HTTPException(status_code=503, detail="Transaction source is temporarily unavailable.")

    # 404 (not 403) for an out-of-scope id: an existing transaction belonging to
    # another distributor must be indistinguishable from one that does not exist,
    # otherwise the endpoint becomes an existence oracle (mirrors
    # dependencies.assert_brand_group_allowed).
    if not row:
        logger.info("ext_tx: denied/missing transaction %s for user %s",
                    ext_visit_id, current_user.username)
        raise HTTPException(status_code=404, detail="Not found")

    items = bq.query(f"""
        SELECT ext_visit_item_id, sku_id, sku_name, brand, category,
               qty, stp, demand, line_value
        FROM {_tbl('ext_visit_item')}
        WHERE ext_visit_id = @id
        ORDER BY sku_name, sku_id
    """, [BQClient.p("id", "STRING", ext_visit_id)])

    detail = ExtTransactionDetail(**_row_to_transaction(row).model_dump())
    detail.items = [
        ExtTransactionItem(
            ext_visit_item_id=i.get("ext_visit_item_id") or "",
            sku_id=i.get("sku_id"), sku_name=i.get("sku_name"),
            brand=i.get("brand"), category=i.get("category"),
            qty=i.get("qty"), stp=i.get("stp"), demand=i.get("demand"),
            line_value=i.get("line_value"),
        )
        for i in items
    ]
    return detail
