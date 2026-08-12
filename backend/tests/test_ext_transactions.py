"""
Unit tests for external distributor transactions.

BQ-free: every test exercises pure functions (parsing, mapping, dedup, join,
totals) or SQL-fragment construction. Nothing here opens a BigQuery client, so
the suite runs without credentials.

Run: pytest backend/tests/test_ext_transactions.py -q
"""
from datetime import date, datetime, timezone

import pytest

from models.auth import UserContext
from routers.ext_transaction import distributor_scope
from services.ext_transactions import (
    ExtVisitItem,
    item_identity,
    map_item_row,
    map_visit_row,
    parse_csv_text,
    parse_number,
    parse_source_date,
    parse_source_timestamp,
    transform,
)


# ── Number parsing (workbook convention: comma = thousands separator) ─────────

@pytest.mark.parametrize("raw,expected", [
    ("89,320", 89320.0),          # the workbook's own sku.stp format
    ("107,030", 107030.0),
    ("1,234,567.89", 1234567.89),
    ("1500", 1500.0),
    ("12.5", 12.5),
    ("1,5", 1.5),                 # comma NOT grouping 3 digits → decimal comma
    ("Rp 89,320", 89320.0),
    ("-5", -5.0),
    ("", None),
    ("   ", None),
    ("#N/A", None),
    ("#REF!", None),
    (None, None),
    ("abc", None),
    (1234, 1234.0),
    (12.5, 12.5),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


# ── Date parsing (day-first, padded or not) ──────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("07/01/2026", date(2026, 1, 7)),      # DD/MM/YYYY — 7 January, not 1 July
    ("7/1/2026", date(2026, 1, 7)),        # unpadded, same meaning
    ("31/12/2025", date(2025, 12, 31)),
    ("2026-01-07", date(2026, 1, 7)),
    ("", None),
    ("not-a-date", None),
])
def test_parse_source_date(raw, expected):
    assert parse_source_date(raw) == expected


def test_day_first_is_not_month_first():
    """The regression this guards: reading 07/01/2026 as 1 July would silently
    move a transaction six months. Source proven day-first (docs/current/17)."""
    assert parse_source_date("07/01/2026").month == 1


# ── Timestamp parsing ────────────────────────────────────────────────────────

def test_explicit_utc_is_honoured():
    ts = parse_source_timestamp("2026-06-12T05:10:13.452Z")
    assert ts == datetime(2026, 6, 12, 5, 10, 13, 452000, tzinfo=timezone.utc)


def test_naive_timestamp_is_read_as_jakarta_wall_time():
    """A naive value is WIB (UTC+7), so 05:10 local is 22:10 UTC the day before.
    Reading it as UTC instead would date-shift the transaction."""
    ts = parse_source_timestamp("2026-06-12 05:10:13")
    assert ts == datetime(2026, 6, 11, 22, 10, 13, tzinfo=timezone.utc)


def test_calendar_date_is_never_timezone_shifted():
    """visit_date is a calendar day, not an instant — no offset may be applied."""
    assert parse_source_date("12/08/2026") == date(2026, 8, 12)


# ── Row mapping ──────────────────────────────────────────────────────────────

def _visit_row(**over):
    row = {
        "visit_id": "V-1", "schedule_id": "S-1", "visit_type": "PJP",
        "username": "GTIDST2722", "store_id": "IWCJ00001", "visit_date": "12/08/2026",
        "checkin_time": "2026-08-12T01:00:00Z", "checkout_time": "2026-08-12T01:30:00Z",
        "total_demand": "450,000", "effective_call": "YES", "visit_status": "COMPLETED",
    }
    row.update(over)
    return row


def test_map_visit_row_happy_path():
    v, err = map_visit_row(_visit_row())
    assert err is None
    assert v.ext_visit_id == "V-1"
    assert v.visit_date == date(2026, 8, 12)
    assert v.source_username == "GTIDST2722"
    assert v.source_store_id == "IWCJ00001"
    assert v.source_total_demand == 450000.0


def test_visit_without_id_is_rejected():
    v, err = map_visit_row(_visit_row(visit_id=""))
    assert v is None and "visit_id" in err


def test_visit_date_falls_back_to_checkin():
    v, err = map_visit_row(_visit_row(visit_date=""))
    assert err is None
    # 01:00Z = 08:00 WIB on the same calendar day
    assert v.visit_date == date(2026, 8, 12)


def test_visit_with_no_date_at_all_is_rejected():
    v, err = map_visit_row(_visit_row(visit_date="", checkin_time=""))
    assert v is None and "visit_date" in err


def test_spreadsheet_error_markers_become_null_not_text():
    v, _ = map_visit_row(_visit_row(username="#N/A"))
    assert v.source_username is None


def test_negative_quantity_is_rejected():
    it, err = map_item_row({"visit_id": "V-1", "sku_id": "S1", "qty": "-3"}, 0)
    assert it is None and "negative" in err


def test_item_identity_is_deterministic_without_a_source_id():
    row = {"visit_id": "V-1", "sku_id": "SKU-9"}
    assert item_identity(row, 0) == item_identity(row, 0)
    assert item_identity(row, 0) != item_identity(row, 1)


def test_item_identity_prefers_the_source_id():
    assert item_identity({"visit_item_id": "I-7", "visit_id": "V-1"}, 3) == "I-7"


# ── The core guarantee: 1 visit + N items = 1 transaction ────────────────────

def test_one_visit_with_five_items_is_one_transaction():
    items = [{"visit_item_id": f"I-{i}", "visit_id": "V-1", "sku_id": f"S{i}",
              "qty": "2", "stp": "10,000", "demand": "20,000"} for i in range(5)]
    visits, res = transform([_visit_row()], items)
    assert len(visits) == 1
    assert visits[0].item_count == 5
    assert len(visits[0].items) == 5
    assert res.orphan_items == 0


def test_duplicate_visit_ids_collapse_to_one_transaction():
    rows = [_visit_row(), _visit_row(visit_status="AMENDED")]
    visits, res = transform(rows, [])
    assert len(visits) == 1
    assert res.duplicate_visits == 1
    assert visits[0].visit_status == "AMENDED"  # last occurrence wins


def test_visit_without_items_is_kept():
    """LEFT JOIN semantics — a transaction with incomplete detail still belongs
    in the history rather than vanishing."""
    visits, res = transform([_visit_row()], [])
    assert len(visits) == 1
    assert visits[0].item_count == 0
    assert visits[0].computed_value == 0


def test_orphan_items_are_dropped_and_counted():
    items = [{"visit_item_id": "I-1", "visit_id": "GHOST", "sku_id": "S1", "qty": "1", "stp": "5"}]
    visits, res = transform([_visit_row()], items)
    assert res.orphan_items == 1
    assert visits[0].item_count == 0


def test_duplicate_item_rows_do_not_inflate_the_transaction():
    dup = {"visit_item_id": "I-1", "visit_id": "V-1", "sku_id": "S1", "qty": "2", "demand": "20,000"}
    visits, _ = transform([_visit_row()], [dict(dup), dict(dup)])
    assert visits[0].item_count == 1
    assert visits[0].computed_value == 20000


# ── Calculation rules (§18) ──────────────────────────────────────────────────

def test_line_value_prefers_the_sources_own_demand():
    it = ExtVisitItem("I", "V", qty=3, stp=10000, demand=25000)
    assert it.line_value == 25000  # source value wins, not 30000


def test_line_value_falls_back_to_qty_times_price():
    it = ExtVisitItem("I", "V", qty=3, stp=10000, demand=None)
    assert it.line_value == 30000


def test_computed_totals_come_from_items():
    items = [
        {"visit_item_id": "I-1", "visit_id": "V-1", "sku_id": "A", "qty": "10", "stp": "20,000", "demand": "200,000"},
        {"visit_item_id": "I-2", "visit_id": "V-1", "sku_id": "B", "qty": "5",  "stp": "30,000", "demand": "150,000"},
        {"visit_item_id": "I-3", "visit_id": "V-1", "sku_id": "C", "qty": "2",  "stp": "50,000", "demand": "100,000"},
    ]
    visits, _ = transform([_visit_row()], items)
    v = visits[0]
    assert v.computed_qty == 17
    assert v.computed_value == 450000


def test_mismatch_flagged_when_source_total_disagrees():
    items = [{"visit_item_id": "I-1", "visit_id": "V-1", "sku_id": "A", "qty": "1", "demand": "100"}]
    visits, res = transform([_visit_row(total_demand="999,999")], items)
    assert visits[0].total_mismatch is True
    assert res.total_mismatches == 1


def test_no_mismatch_within_one_rupiah():
    items = [{"visit_item_id": "I-1", "visit_id": "V-1", "sku_id": "A", "qty": "1", "demand": "450,000"}]
    visits, res = transform([_visit_row(total_demand="450,000")], items)
    assert visits[0].total_mismatch is False
    assert res.total_mismatches == 0


def test_source_total_is_never_overwritten():
    items = [{"visit_item_id": "I-1", "visit_id": "V-1", "sku_id": "A", "qty": "1", "demand": "100"}]
    visits, _ = transform([_visit_row(total_demand="999,999")], items)
    assert visits[0].source_total_demand == 999999
    assert visits[0].computed_value == 100


def test_invalid_rows_are_counted_not_silently_dropped():
    rows = [_visit_row(), _visit_row(visit_id=""), _visit_row(visit_id="V-2", visit_date="", checkin_time="")]
    visits, res = transform(rows, [])
    assert len(visits) == 1
    assert res.invalid_visits == 2
    assert len(res.errors) == 2


# ── Authorization (§9) — server-side, fails closed ───────────────────────────

def _user(role, dist=None):
    return UserContext(user_id="u1", username="tester", role=role, distributor_code=dist)


def test_ho_admin_is_unscoped():
    clause, params = distributor_scope(_user("ho_admin"))
    assert clause == "" and params == []


def test_dm_is_pinned_to_their_own_distributor():
    clause, params = distributor_scope(_user("dm", "DST105"))
    assert "v.distributor_code = @scope_dist" in clause
    assert params[0].value == "DST105"


def test_dm_without_a_distributor_sees_nothing():
    """Fail CLOSED: a misconfigured dm must not fall through to every row."""
    clause, params = distributor_scope(_user("dm", None))
    assert clause == "AND 1=0" and params == []


@pytest.mark.parametrize("role", ["spv", "asm", "salesman", "demo", "", "admin"])
def test_every_other_role_sees_nothing(role):
    clause, _ = distributor_scope(_user(role, "DST105"))
    assert clause == "AND 1=0"


def test_scope_clause_cannot_be_widened_by_a_forged_parameter():
    """The scope predicate is ANDed in first and never reads user input, so a
    forged salesman_sk/distributor_code can only ever match fewer rows."""
    from routers.ext_transaction import _filters
    where, params = _filters(_user("dm", "DST105"), None, None, "OTHER-DIST-SALESMAN", None, None)
    assert where.startswith("AND v.distributor_code = @scope_dist")
    assert any(p.value == "DST105" for p in params)


# ── CSV reading ──────────────────────────────────────────────────────────────

def test_parse_csv_normalizes_headers_and_skips_blank_rows():
    rows = parse_csv_text('"Visit ID","QTY"\r\n"V-1","2"\r\n"",""\r\n')
    assert rows == [{"visit_id": "V-1", "qty": "2"}]


def test_header_only_sheet_yields_no_rows():
    """The live source is currently header-only; that must read as zero
    transactions, not as one blank transaction."""
    assert parse_csv_text('"visit_id","store_id"\r\n') == []
    visits, res = transform([], [])
    assert visits == [] and res.visits_read == 0
