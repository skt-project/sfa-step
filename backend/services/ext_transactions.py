"""
External distributor transactions — ingestion from a Google Spreadsheet.

SEPARATION RULE (docs/current/17). This module never reads or writes step_visit,
step_visit_item, or any other SFA transaction table. Its only destination is
ext_visit / ext_visit_item / ext_transaction_sync_log. The SFA pipeline
(routers/visit.py) and this one share no code path and no table.

Reading the sheet
-----------------
The spreadsheet is fetched through Google's CSV-export endpoint with httpx
(already a dependency) — no Sheets API client and no service-account scope change
while the sheet stays link-readable. `run_sync` takes any `reader(gid) -> rows`
callable, so a credentialed reader can be swapped in later without touching the
mapping, dedup, or write logic (and tests pass rows inline).

Source conventions (established from the populated tabs of the same workbook,
2026-08-13 — see docs/current/17 §data conventions):
  * `visit_date`      — day-first `DD/MM/YYYY`, sometimes unpadded (`7/1/2026`).
                        A calendar date, NOT an instant: stored as DATE, never
                        timezone-shifted.
  * timestamps        — ISO-8601 with an explicit `Z` (`2026-06-12T05:10:13.452Z`),
                        i.e. already UTC. A naive timestamp (no offset) is read as
                        Asia/Jakarta wall time, which is the operating timezone.
  * numbers           — thousands-separated with commas (`89,320` = 89320 IDR),
                        `.` is the decimal point.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Asia/Jakarta. Used only for naive source timestamps; explicit-offset values are
# honoured as given. Python's stdlib has no IANA db on Windows, and WIB has had no
# DST since 1964, so a fixed offset is exact here.
WIB = timezone(timedelta(hours=7))

CHUNK = 500  # rows per BigQuery MERGE, matching routers/import_export.py


class SheetUnavailable(RuntimeError):
    """The external source could not be read. Never surfaced verbatim to users."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

SheetReader = Callable[[str], list[dict]]


def csv_export_url(gid: str, spreadsheet_id: str | None = None) -> str:
    sid = spreadsheet_id or settings.ext_tx_spreadsheet_id
    return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"


def parse_csv_text(text: str) -> list[dict]:
    """CSV text → list of dicts with normalized (lower, underscored) headers."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames is None:
        return []
    reader.fieldnames = [(h or "").strip().lower().replace(" ", "_") for h in reader.fieldnames]
    return [r for r in reader if any((v or "").strip() for v in r.values())]


def fetch_sheet_rows(gid: str) -> list[dict]:
    """Default reader: pull one tab as CSV. Raises SheetUnavailable on any failure."""
    url = csv_export_url(gid)
    try:
        resp = httpx.get(url, timeout=settings.ext_tx_timeout_s, follow_redirects=True)
    except httpx.HTTPError as exc:
        # Log the class of failure, never the URL's credentials/cookies.
        logger.warning("ext_tx: sheet fetch failed gid=%s err=%s", gid, type(exc).__name__)
        raise SheetUnavailable(f"fetch failed for gid {gid}") from exc
    if resp.status_code != 200:
        logger.warning("ext_tx: sheet fetch gid=%s status=%s", gid, resp.status_code)
        raise SheetUnavailable(f"HTTP {resp.status_code} for gid {gid}")
    ctype = resp.headers.get("content-type", "")
    if "csv" not in ctype.lower():
        # Google serves an HTML sign-in page when the sheet is not readable.
        logger.warning("ext_tx: sheet gid=%s returned %s — not shared?", gid, ctype)
        raise SheetUnavailable(f"gid {gid} is not readable (got {ctype})")
    return parse_csv_text(resp.text)


# ---------------------------------------------------------------------------
# Parsing — pure, unit-tested
# ---------------------------------------------------------------------------

# A comma that groups thousands: preceded by a digit, followed by exactly 3 digits
# that are not themselves followed by another digit. "89,320" → "89320".
_THOUSANDS_SEP = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")
_CURRENCY = re.compile(r"(?i)\b(rp|idr)\b\.?")


def parse_number(raw: Any) -> float | None:
    """Source number → float. Handles `89,320`, `1,234,567.89`, `1.5`, `Rp 12.000`.

    A comma is a thousands separator (the workbook's convention); a comma that is
    NOT grouping three digits is treated as a decimal comma so id-ID input still
    parses rather than silently losing precision.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    s = _CURRENCY.sub("", s).replace("\u00a0", "").replace(" ", "")
    if not s or s in {"-", "#N/A", "#REF!", "#VALUE!", "N/A"}:
        return None
    s = _THOUSANDS_SEP.sub("", s)
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(raw: Any) -> int | None:
    n = parse_number(raw)
    return int(n) if n is not None else None


def parse_source_date(raw: Any) -> date | None:
    """Source date → date. Day-first `DD/MM/YYYY` (padded or not), or ISO."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    ts = parse_source_timestamp(s)
    return ts.date() if ts else None


def parse_source_timestamp(raw: Any) -> datetime | None:
    """Source timestamp → tz-aware UTC datetime.

    An explicit offset (`...Z`, `+07:00`) is honoured as given. A naive value is
    read as Asia/Jakarta wall time — the operating timezone — so a WIB-local
    string never lands a day early after conversion.
    """
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw or "").strip()
        if not s:
            return None
        dt = None
        iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=WIB)
    return dt.astimezone(timezone.utc)


def _clean(raw: Any) -> str | None:
    """Trim a source string; spreadsheet error markers become NULL, not text."""
    s = str(raw or "").strip()
    if not s or s in {"#N/A", "#REF!", "#VALUE!", "#DIV/0!", "N/A", "-"}:
        return None
    return s


# ---------------------------------------------------------------------------
# Canonical model
# ---------------------------------------------------------------------------


@dataclass
class ExtVisitItem:
    ext_visit_item_id: str
    ext_visit_id: str
    sku_id: str | None = None
    sku_name: str | None = None
    brand: str | None = None
    category: str | None = None
    qty: float | None = None
    stp: float | None = None
    demand: float | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None

    @property
    def line_value(self) -> float | None:
        """Authoritative line value: the source's own `demand` when it states one,
        otherwise qty × stp. The source value is never silently overwritten (§18)."""
        if self.demand is not None and self.demand != 0:
            return self.demand
        if self.qty is not None and self.stp is not None:
            return round(self.qty * self.stp, 2)
        return self.demand


@dataclass
class ExtVisit:
    ext_visit_id: str
    source_schedule_id: str | None = None
    source_visit_type: str | None = None
    source_username: str | None = None
    source_store_id: str | None = None
    visit_date: date | None = None
    checkin_time: datetime | None = None
    checkout_time: datetime | None = None
    checkin_latitude: float | None = None
    checkin_longitude: float | None = None
    checkin_distance_meter: float | None = None
    checkin_photo_url: str | None = None
    checkout_latitude: float | None = None
    checkout_longitude: float | None = None
    checkout_distance_meter: float | None = None
    checkout_photo_url: str | None = None
    notes: str | None = None
    duration_minutes: int | None = None
    source_total_demand: float | None = None
    effective_call: str | None = None
    visit_status: str | None = None
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    # Derived from items (never from the source header)
    item_count: int = 0
    computed_qty: float = 0.0
    computed_value: float = 0.0
    items: list[ExtVisitItem] = field(default_factory=list)

    @property
    def total_mismatch(self) -> bool:
        """TRUE when the source's stated total disagrees with the item sum by more
        than 1 rupiah. Reported, never auto-corrected."""
        if self.source_total_demand is None:
            return False
        return abs(self.source_total_demand - self.computed_value) > 1.0


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def map_visit_row(row: dict) -> tuple[ExtVisit | None, str | None]:
    """Source `visit` row → ExtVisit, or (None, reason) when unusable."""
    vid = _clean(row.get("visit_id"))
    if not vid:
        return None, "missing visit_id"
    visit_date = parse_source_date(row.get("visit_date"))
    if visit_date is None:
        # Fall back to the check-in instant before rejecting — a transaction with
        # a check-in but a blank date column is still a real transaction.
        ci = parse_source_timestamp(row.get("checkin_time"))
        if ci is None:
            return None, "missing/unparseable visit_date"
        visit_date = ci.astimezone(WIB).date()
    return ExtVisit(
        ext_visit_id=vid,
        source_schedule_id=_clean(row.get("schedule_id")),
        source_visit_type=_clean(row.get("visit_type")),
        source_username=_clean(row.get("username")),
        source_store_id=_clean(row.get("store_id")),
        visit_date=visit_date,
        checkin_time=parse_source_timestamp(row.get("checkin_time")),
        checkout_time=parse_source_timestamp(row.get("checkout_time")),
        checkin_latitude=parse_number(row.get("checkin_latitude")),
        checkin_longitude=parse_number(row.get("checkin_longitude")),
        checkin_distance_meter=parse_number(row.get("checkin_distance_meter")),
        checkin_photo_url=_clean(row.get("checkin_photo_url")),
        checkout_latitude=parse_number(row.get("checkout_latitude")),
        checkout_longitude=parse_number(row.get("checkout_longitude")),
        checkout_distance_meter=parse_number(row.get("checkout_distance_meter")),
        checkout_photo_url=_clean(row.get("checkout_photo_url")),
        notes=_clean(row.get("notes")),
        duration_minutes=parse_int(row.get("duration_minutes")),
        source_total_demand=parse_number(row.get("total_demand")),
        effective_call=_clean(row.get("effective_call")),
        visit_status=_clean(row.get("visit_status")),
        source_created_at=parse_source_timestamp(row.get("created_at")),
        source_updated_at=parse_source_timestamp(row.get("updated_at")),
    ), None


def item_identity(row: dict, ordinal: int) -> str:
    """Stable item key. Uses the source's own id when present; otherwise a
    deterministic hash so re-syncing the same sheet does not duplicate rows."""
    explicit = _clean(row.get("visit_item_id"))
    if explicit:
        return explicit
    seed = f"{_clean(row.get('visit_id')) or ''}|{_clean(row.get('sku_id')) or ''}|{ordinal}"
    return hashlib.sha1(seed.encode()).hexdigest()


def map_item_row(row: dict, ordinal: int = 0) -> tuple[ExtVisitItem | None, str | None]:
    vid = _clean(row.get("visit_id"))
    if not vid:
        return None, "missing visit_id"
    qty = parse_number(row.get("qty"))
    if qty is not None and qty < 0:
        return None, f"negative qty ({qty})"
    stp = parse_number(row.get("stp"))
    if stp is not None and stp < 0:
        return None, f"negative stp ({stp})"
    return ExtVisitItem(
        ext_visit_item_id=item_identity(row, ordinal),
        ext_visit_id=vid,
        sku_id=_clean(row.get("sku_id")),
        qty=qty,
        stp=stp,
        demand=parse_number(row.get("demand")),
        source_created_at=parse_source_timestamp(row.get("created_at")),
        source_updated_at=parse_source_timestamp(row.get("updated_at")),
    ), None


def build_sku_lookup(rows: list[dict]) -> dict[str, dict]:
    """sku_id → {sku_name, brand, category} from the workbook's own `sku` tab."""
    out: dict[str, dict] = {}
    for r in rows:
        sid = _clean(r.get("sku_id"))
        if not sid:
            continue
        out[sid] = {
            "sku_name": _clean(r.get("sku_name")),
            "brand": _clean(r.get("brand")),
            "category": _clean(r.get("category")),
        }
    return out


# ---------------------------------------------------------------------------
# Dedup + assembly — the §7/§17 guarantee: 1 source visit = 1 transaction
# ---------------------------------------------------------------------------


def dedupe_visits(visits: list[ExtVisit]) -> tuple[list[ExtVisit], int]:
    """Collapse repeated visit_ids. Last occurrence wins (sheets are appended to,
    so a later row is the correction). Returns (unique, duplicates_dropped)."""
    by_id: dict[str, ExtVisit] = {}
    dupes = 0
    for v in visits:
        if v.ext_visit_id in by_id:
            dupes += 1
        by_id[v.ext_visit_id] = v
    return list(by_id.values()), dupes


def dedupe_items(items: list[ExtVisitItem]) -> tuple[list[ExtVisitItem], int]:
    by_id: dict[str, ExtVisitItem] = {}
    dupes = 0
    for it in items:
        if it.ext_visit_item_id in by_id:
            dupes += 1
        by_id[it.ext_visit_item_id] = it
    return list(by_id.values()), dupes


def assemble(
    visits: list[ExtVisit],
    items: list[ExtVisitItem],
    sku_lookup: dict[str, dict] | None = None,
) -> tuple[list[ExtVisit], int]:
    """Attach items to their parent visit and derive the header totals.

    Items whose parent visit is absent are dropped and counted as orphans — they
    would otherwise become invisible value. A visit with no items is KEPT (LEFT
    JOIN semantics, §7): a real transaction with incomplete detail still belongs
    in the history. Returns (visits, orphan_count).
    """
    index = {v.ext_visit_id: v for v in visits}
    orphans = 0
    for it in items:
        parent = index.get(it.ext_visit_id)
        if parent is None:
            orphans += 1
            continue
        if sku_lookup and it.sku_id:
            meta = sku_lookup.get(it.sku_id)
            if meta:
                it.sku_name = meta.get("sku_name")
                it.brand = meta.get("brand")
                it.category = meta.get("category")
        parent.items.append(it)

    for v in visits:
        v.item_count = len(v.items)
        v.computed_qty = round(sum(i.qty or 0.0 for i in v.items), 4)
        v.computed_value = round(sum(i.line_value or 0.0 for i in v.items), 2)
    return visits, orphans


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    batch_id: str
    status: str = "RUNNING"
    visits_read: int = 0
    items_read: int = 0
    visits_written: int = 0
    items_written: int = 0
    invalid_visits: int = 0
    invalid_items: int = 0
    duplicate_visits: int = 0
    orphan_items: int = 0
    unmapped_stores: int = 0
    unmapped_salesmen: int = 0
    total_mismatches: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "batch_id": self.batch_id, "status": self.status,
            "visits_read": self.visits_read, "items_read": self.items_read,
            "visits_written": self.visits_written, "items_written": self.items_written,
            "invalid_visits": self.invalid_visits, "invalid_items": self.invalid_items,
            "duplicate_visits": self.duplicate_visits, "orphan_items": self.orphan_items,
            "unmapped_stores": self.unmapped_stores, "unmapped_salesmen": self.unmapped_salesmen,
            "total_mismatches": self.total_mismatches, "errors": self.errors[:20],
        }


def transform(
    visit_rows: list[dict],
    item_rows: list[dict],
    sku_rows: list[dict] | None = None,
) -> tuple[list[ExtVisit], SyncResult]:
    """Pure source-rows → canonical transactions. No I/O; the unit tests' entry point."""
    res = SyncResult(batch_id="dry-run")
    res.visits_read = len(visit_rows)
    res.items_read = len(item_rows)

    visits: list[ExtVisit] = []
    for r in visit_rows:
        v, err = map_visit_row(r)
        if v is None:
            res.invalid_visits += 1
            if err:
                res.errors.append(f"visit: {err}")
            continue
        visits.append(v)

    items: list[ExtVisitItem] = []
    for i, r in enumerate(item_rows):
        it, err = map_item_row(r, i)
        if it is None:
            res.invalid_items += 1
            if err:
                res.errors.append(f"visit_item: {err}")
            continue
        items.append(it)

    visits, res.duplicate_visits = dedupe_visits(visits)
    items, _ = dedupe_items(items)
    visits, res.orphan_items = assemble(visits, items, build_sku_lookup(sku_rows or []))
    res.total_mismatches = sum(1 for v in visits if v.total_mismatch)
    return visits, res


# ── BigQuery write ──────────────────────────────────────────────────────────


def _lit(v: Any) -> str:
    """Escape a value as a BigQuery literal. Mirrors import_export._str_lit for
    strings, and emits typed NULLs so MERGE never coerces a missing number to 0."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, datetime):
        return f'TIMESTAMP "{v.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")} UTC"'
    if isinstance(v, date):
        return f'DATE "{v.isoformat()}"'
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", "")
    return f'"{s}"'


_VISIT_STRUCT = (
    "STRUCT<ext_visit_id STRING, source_schedule_id STRING, source_visit_type STRING, "
    "source_username STRING, source_store_id STRING, visit_date DATE, "
    "checkin_time TIMESTAMP, checkout_time TIMESTAMP, checkin_latitude FLOAT64, "
    "checkin_longitude FLOAT64, checkin_distance_meter FLOAT64, checkin_photo_url STRING, "
    "checkout_latitude FLOAT64, checkout_longitude FLOAT64, checkout_distance_meter FLOAT64, "
    "checkout_photo_url STRING, notes STRING, duration_minutes INT64, "
    "source_total_demand FLOAT64, effective_call STRING, visit_status STRING, "
    "source_created_at TIMESTAMP, source_updated_at TIMESTAMP, item_count INT64, "
    "computed_qty FLOAT64, computed_value FLOAT64, total_mismatch BOOL, row_hash STRING>"
)

_ITEM_STRUCT = (
    "STRUCT<ext_visit_item_id STRING, ext_visit_id STRING, sku_id STRING, sku_name STRING, "
    "brand STRING, category STRING, qty FLOAT64, stp FLOAT64, demand FLOAT64, "
    "line_value FLOAT64, source_created_at TIMESTAMP, source_updated_at TIMESTAMP>"
)


def _visit_row_hash(v: ExtVisit) -> str:
    seed = "|".join(str(x) for x in (
        v.source_schedule_id, v.source_username, v.source_store_id, v.visit_date,
        v.checkin_time, v.checkout_time, v.source_total_demand, v.effective_call,
        v.visit_status, v.item_count, v.computed_qty, v.computed_value,
    ))
    return hashlib.sha1(seed.encode()).hexdigest()


def _visit_struct_literal(v: ExtVisit) -> str:
    return "(" + ", ".join(_lit(x) for x in (
        v.ext_visit_id, v.source_schedule_id, v.source_visit_type, v.source_username,
        v.source_store_id, v.visit_date, v.checkin_time, v.checkout_time,
        v.checkin_latitude, v.checkin_longitude, v.checkin_distance_meter, v.checkin_photo_url,
        v.checkout_latitude, v.checkout_longitude, v.checkout_distance_meter, v.checkout_photo_url,
        v.notes, v.duration_minutes, v.source_total_demand, v.effective_call, v.visit_status,
        v.source_created_at, v.source_updated_at, v.item_count, v.computed_qty,
        v.computed_value, v.total_mismatch, _visit_row_hash(v),
    )) + ")"


def _item_struct_literal(it: ExtVisitItem) -> str:
    return "(" + ", ".join(_lit(x) for x in (
        it.ext_visit_item_id, it.ext_visit_id, it.sku_id, it.sku_name, it.brand,
        it.category, it.qty, it.stp, it.demand, it.line_value,
        it.source_created_at, it.source_updated_at,
    )) + ")"


def _tbl(name: str) -> str:
    return f"`{settings.bq_project}.{settings.bq_dataset}.{name}`"


def _write_visits(bq, visits: list[ExtVisit], batch_id: str) -> int:
    written = 0
    for start in range(0, len(visits), CHUNK):
        chunk = visits[start:start + CHUNK]
        vals = ", ".join(_visit_struct_literal(v) for v in chunk)
        bq.execute(f"""
        MERGE {_tbl('ext_visit')} t
        USING (SELECT * FROM UNNEST(ARRAY<{_VISIT_STRUCT}>[{vals}])) s
        ON t.ext_visit_id = s.ext_visit_id
        WHEN MATCHED THEN UPDATE SET
          source_schedule_id = s.source_schedule_id, source_visit_type = s.source_visit_type,
          source_username = s.source_username, source_store_id = s.source_store_id,
          visit_date = s.visit_date, checkin_time = s.checkin_time, checkout_time = s.checkout_time,
          checkin_latitude = s.checkin_latitude, checkin_longitude = s.checkin_longitude,
          checkin_distance_meter = s.checkin_distance_meter, checkin_photo_url = s.checkin_photo_url,
          checkout_latitude = s.checkout_latitude, checkout_longitude = s.checkout_longitude,
          checkout_distance_meter = s.checkout_distance_meter, checkout_photo_url = s.checkout_photo_url,
          notes = s.notes, duration_minutes = s.duration_minutes,
          source_total_demand = s.source_total_demand, effective_call = s.effective_call,
          visit_status = s.visit_status, source_created_at = s.source_created_at,
          source_updated_at = s.source_updated_at, item_count = s.item_count,
          computed_qty = s.computed_qty, computed_value = s.computed_value,
          total_mismatch = s.total_mismatch, row_hash = s.row_hash,
          batch_id = @batch, synced_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (
          ext_visit_id, source_schedule_id, source_visit_type, source_username, source_store_id,
          visit_date, checkin_time, checkout_time, checkin_latitude, checkin_longitude,
          checkin_distance_meter, checkin_photo_url, checkout_latitude, checkout_longitude,
          checkout_distance_meter, checkout_photo_url, notes, duration_minutes,
          source_total_demand, effective_call, visit_status, source_created_at, source_updated_at,
          item_count, computed_qty, computed_value, total_mismatch, row_hash, batch_id, synced_at)
        VALUES (
          s.ext_visit_id, s.source_schedule_id, s.source_visit_type, s.source_username, s.source_store_id,
          s.visit_date, s.checkin_time, s.checkout_time, s.checkin_latitude, s.checkin_longitude,
          s.checkin_distance_meter, s.checkin_photo_url, s.checkout_latitude, s.checkout_longitude,
          s.checkout_distance_meter, s.checkout_photo_url, s.notes, s.duration_minutes,
          s.source_total_demand, s.effective_call, s.visit_status, s.source_created_at, s.source_updated_at,
          s.item_count, s.computed_qty, s.computed_value, s.total_mismatch, s.row_hash,
          @batch, CURRENT_TIMESTAMP())
        """, [bq.p("batch", "STRING", batch_id)])
        written += len(chunk)
    return written


def _write_items(bq, items: list[ExtVisitItem], batch_id: str) -> int:
    written = 0
    for start in range(0, len(items), CHUNK):
        chunk = items[start:start + CHUNK]
        vals = ", ".join(_item_struct_literal(i) for i in chunk)
        bq.execute(f"""
        MERGE {_tbl('ext_visit_item')} t
        USING (SELECT * FROM UNNEST(ARRAY<{_ITEM_STRUCT}>[{vals}])) s
        ON t.ext_visit_item_id = s.ext_visit_item_id
        WHEN MATCHED THEN UPDATE SET
          ext_visit_id = s.ext_visit_id, sku_id = s.sku_id, sku_name = s.sku_name,
          brand = s.brand, category = s.category, qty = s.qty, stp = s.stp,
          demand = s.demand, line_value = s.line_value,
          source_created_at = s.source_created_at, source_updated_at = s.source_updated_at,
          batch_id = @batch, synced_at = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (
          ext_visit_item_id, ext_visit_id, sku_id, sku_name, brand, category,
          qty, stp, demand, line_value, source_created_at, source_updated_at, batch_id, synced_at)
        VALUES (
          s.ext_visit_item_id, s.ext_visit_id, s.sku_id, s.sku_name, s.brand, s.category,
          s.qty, s.stp, s.demand, s.line_value, s.source_created_at, s.source_updated_at,
          @batch, CURRENT_TIMESTAMP())
        """, [bq.p("batch", "STRING", batch_id)])
        written += len(chunk)
    return written


def _resolve_mapping(bq, batch_id: str) -> tuple[int, int]:
    """Resolve sheet identifiers onto STEP masters, SQL-side (no per-row lookup).

    Store → dim_outlet gives `distributor_code`, which is the authorization key:
    STEP already scopes a dm by the OUTLET's distributor (routers/visit.py), and
    this feature follows that precedent. Re-run on every sync, so a master-data
    correction is picked up without a backfill.
    """
    bq.execute(f"""
    UPDATE {_tbl('ext_visit')} v
    SET salesman_sk = s.salesman_sk, salesman_name = s.salesman_name
    FROM (
      SELECT source_salesman_code, salesman_sk, salesman_name
      FROM {settings.table('dim_salesman')}
      QUALIFY ROW_NUMBER() OVER (PARTITION BY source_salesman_code ORDER BY is_active DESC) = 1
    ) s
    WHERE v.batch_id = @batch AND v.source_username = s.source_salesman_code
    """, [bq.p("batch", "STRING", batch_id)])

    bq.execute(f"""
    UPDATE {_tbl('ext_visit')} v
    SET outlet_sk = o.outlet_sk, store_name = o.store_name,
        distributor_code = o.distributor_code, brand_group = o.brand_group
    FROM (
      SELECT source_outlet_code, outlet_sk, store_name, distributor_code, brand_group
      FROM {settings.table('dim_outlet')}
      QUALIFY ROW_NUMBER() OVER (PARTITION BY source_outlet_code ORDER BY outlet_sk) = 1
    ) o
    WHERE v.batch_id = @batch AND v.source_store_id = o.source_outlet_code
    """, [bq.p("batch", "STRING", batch_id)])

    row = bq.query_one(f"""
    SELECT COUNT(DISTINCT IF(outlet_sk IS NULL, source_store_id, NULL)) AS stores,
           COUNT(DISTINCT IF(salesman_sk IS NULL, source_username, NULL)) AS salesmen
    FROM {_tbl('ext_visit')} WHERE batch_id = @batch
    """, [bq.p("batch", "STRING", batch_id)]) or {}
    return int(row.get("stores") or 0), int(row.get("salesmen") or 0)


def _prune_stale(bq, batch_id: str) -> None:
    """Remove rows the source no longer has. The sheet is a full mirror, so any
    row not touched by this batch was deleted upstream."""
    bq.execute(
        f"DELETE FROM {_tbl('ext_visit_item')} WHERE batch_id != @batch OR batch_id IS NULL",
        [bq.p("batch", "STRING", batch_id)],
    )
    bq.execute(
        f"DELETE FROM {_tbl('ext_visit')} WHERE batch_id != @batch OR batch_id IS NULL",
        [bq.p("batch", "STRING", batch_id)],
    )


def _log_run(bq, res: SyncResult, started_at: datetime, error: str | None) -> None:
    try:
        bq.execute(f"""
        INSERT INTO {_tbl('ext_transaction_sync_log')}
          (batch_id, started_at, finished_at, status, triggered_by, visits_read, items_read,
           visits_written, items_written, invalid_visits, duplicate_visits, orphan_items,
           unmapped_stores, unmapped_salesmen, total_mismatches, error)
        VALUES (@batch, @started, CURRENT_TIMESTAMP(), @status, @by, @vr, @ir, @vw, @iw,
                @inv, @dup, @orp, @us, @usm, @tm, @err)
        """, [
            bq.p("batch", "STRING", res.batch_id), bq.p("started", "TIMESTAMP", started_at.isoformat()),
            bq.p("status", "STRING", res.status), bq.p("by", "STRING", getattr(res, "_triggered_by", "") or ""),
            bq.p("vr", "INT64", res.visits_read), bq.p("ir", "INT64", res.items_read),
            bq.p("vw", "INT64", res.visits_written), bq.p("iw", "INT64", res.items_written),
            bq.p("inv", "INT64", res.invalid_visits), bq.p("dup", "INT64", res.duplicate_visits),
            bq.p("orp", "INT64", res.orphan_items), bq.p("us", "INT64", res.unmapped_stores),
            bq.p("usm", "INT64", res.unmapped_salesmen), bq.p("tm", "INT64", res.total_mismatches),
            bq.p("err", "STRING", (error or "")[:1000]),
        ])
    except Exception:  # a log failure must never fail the sync
        logger.exception("ext_tx: could not write sync log for batch %s", res.batch_id)


def run_sync(*, triggered_by: str, reader: SheetReader | None = None) -> SyncResult:
    """Full sync: read the sheet, transform, upsert, resolve mapping, prune, log.

    `reader` defaults to the CSV-export fetcher; pass a callable for tests or for
    a future credentialed reader.
    """
    from services.bq import BQClient

    started_at = datetime.now(timezone.utc)
    batch_id = uuid.uuid4().hex
    read = reader or fetch_sheet_rows

    if not settings.ext_tx_sync_enabled:
        res = SyncResult(batch_id=batch_id, status="FAILED")
        res.errors.append("sync disabled by configuration")
        return res

    try:
        visit_rows = read(settings.ext_tx_visit_gid)
        item_rows = read(settings.ext_tx_visit_item_gid)
        try:
            sku_rows = read(settings.ext_tx_sku_gid)
        except SheetUnavailable:
            sku_rows = []  # product names are an enrichment, not a requirement
    except SheetUnavailable as exc:
        res = SyncResult(batch_id=batch_id, status="FAILED")
        res.errors.append(str(exc))
        setattr(res, "_triggered_by", triggered_by)
        _log_run(BQClient.get(), res, started_at, str(exc))
        logger.warning("ext_tx: sync %s FAILED — source unavailable", batch_id)
        return res

    visits, res = transform(visit_rows, item_rows, sku_rows)
    res.batch_id = batch_id
    setattr(res, "_triggered_by", triggered_by)

    bq = BQClient.get()
    error: str | None = None
    try:
        res.visits_written = _write_visits(bq, visits, batch_id)
        all_items = [i for v in visits for i in v.items]
        res.items_written = _write_items(bq, all_items, batch_id)
        _prune_stale(bq, batch_id)
        res.unmapped_stores, res.unmapped_salesmen = _resolve_mapping(bq, batch_id)
        res.status = "PARTIAL" if (res.invalid_visits or res.orphan_items) else "SUCCESS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        res.status = "FAILED"
        res.errors.append(error)
        logger.exception("ext_tx: sync %s failed during write", batch_id)

    _log_run(bq, res, started_at, error)
    bq.cache.invalidate("ext_tx:")
    logger.info(
        "ext_tx: sync %s %s — %s visits / %s items written, %s invalid, %s orphans, "
        "%s unmapped stores, %s mismatches",
        batch_id, res.status, res.visits_written, res.items_written,
        res.invalid_visits, res.orphan_items, res.unmapped_stores, res.total_mismatches,
    )
    return res
