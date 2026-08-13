"""
BQ-free unit tests for the linked-approval enactment + brand mapping added for
E2E-07 / E2E-04 / E2E-03 (docs/current/13-ecosystem-e2e-audit.md).

The enactment dispatcher is exercised with a fake BQ client that records the DML
it would run, so we verify *what* gets applied without touching BigQuery.
"""
import types

import pytest
from fastapi import HTTPException

from models.auth import UserContext


class FakeCache:
    def invalidate(self, prefix=""):
        pass


class FakeBQ:
    """Records execute() calls; p() just packages params as tuples."""
    def __init__(self):
        self.calls = []
        self.cache = FakeCache()

    @staticmethod
    def p(name, typ, value):
        return (name, typ, value)

    def execute(self, sql, params=None):
        self.calls.append((sql, params or []))


# ── brand_to_group: both spellings fold to a group ────────────────────────────

@pytest.mark.parametrize("brand,expected", [
    ("Skintific", "SKT"), ("SKINTIFIC", "SKT"), ("Timephoria", "SKT"),
    ("Glad2Glow", "G2G"), ("G2G", "G2G"), ("BODIBREZE", "G2G"),
    (None, None), ("", None), ("Totally Unknown", None),
])
def test_brand_to_group(brand, expected):
    from dependencies import brand_to_group
    assert brand_to_group(brand) == expected


# ── assert_brand_name_allowed: blocks only KNOWN other-BU brands ──────────────

def test_brand_name_scope_blocks_other_bu_allows_own_and_unclassified():
    from dependencies import assert_brand_name_allowed
    skt = UserContext(user_id="u", username="asm", role="asm", brand_group="SKT")
    assert_brand_name_allowed(skt, "Skintific")     # own -> ok
    assert_brand_name_allowed(skt, None)             # unclassified -> ok
    assert_brand_name_allowed(skt, "Totally Unknown")  # unmappable -> ok
    with pytest.raises(HTTPException) as e:
        assert_brand_name_allowed(skt, "Glad2Glow")  # known other BU -> 404
    assert e.value.status_code == 404
    # admin bypasses
    assert_brand_name_allowed(UserContext(user_id="a", username="adm", role="ho_admin"), "Glad2Glow")


def test_brand_name_filter_shape():
    from dependencies import brand_name_filter
    admin = UserContext(user_id="a", username="adm", role="ho_admin")
    assert brand_name_filter(admin) == ("", [])
    clause, params = brand_name_filter(
        UserContext(user_id="b", username="asm", role="asm", brand_group="G2G"), col="brand", table_alias="o")
    assert "UPPER(o.brand) IN" in clause and "o.brand IS NULL" in clause
    assert len(params) == 4  # G2G has 4 name spellings


# ── enactment dispatcher ──────────────────────────────────────────────────────

def test_enact_spv_target_applies_amount():
    from routers.approval import _enact_approval
    bq = FakeBQ()
    link = {"entity_type": "spv_target", "entity_id": "T-1", "proposed_value": "1,250"}
    applied = _enact_approval(bq, link, now="2026-07-24T00:00:00Z")
    assert applied is True
    sql, params = bq.calls[0]
    assert "spv_target" in sql and "approval_status = 'approved'" in sql
    assert ("val", "FLOAT64", 1250.0) in params  # comma stripped, coerced to float


def test_enact_outlet_tier_applies_grade():
    from routers.approval import _enact_approval
    bq = FakeBQ()
    link = {"entity_type": "outlet_tier", "entity_id": "555", "proposed_value": "A"}
    assert _enact_approval(bq, link, now="2026-07-24T00:00:00Z") is True
    sql, params = bq.calls[0]
    assert "dim_outlet" in sql and "store_grade" in sql
    assert ("val", "STRING", "A") in params


def test_enact_advisory_request_applies_nothing():
    from routers.approval import _enact_approval
    bq = FakeBQ()
    assert _enact_approval(bq, {"entity_type": None, "proposed_value": "x"}, now="n") is False
    assert _enact_approval(bq, {"entity_type": "spv_target"}, now="n") is False  # no entity_id
    assert bq.calls == []


def test_enact_spv_target_rejects_non_numeric():
    from routers.approval import _enact_approval
    bq = FakeBQ()
    link = {"entity_type": "spv_target", "entity_id": "T-1", "proposed_value": "not-a-number"}
    with pytest.raises(HTTPException) as e:
        _enact_approval(bq, link, now="n")
    assert e.value.status_code == 422
    assert bq.calls == []  # nothing applied on a bad value


# ── decide-scope guard (E2E-04) ───────────────────────────────────────────────

def test_assert_can_decide_scope():
    from routers.approval import _assert_can_decide
    admin = UserContext(user_id="a", username="adm", role="ho_admin")
    skt_asm = UserContext(user_id="b", username="asm", role="asm", brand_group="SKT")
    _assert_can_decide(admin, "G2G")     # admin decides anything
    _assert_can_decide(skt_asm, "SKT")    # own group ok
    _assert_can_decide(skt_asm, None)     # legacy/unscoped ok
    with pytest.raises(HTTPException) as e:
        _assert_can_decide(skt_asm, "G2G")  # other group blocked
    assert e.value.status_code == 403
