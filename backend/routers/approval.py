"""
GET  /approvals                  — list approval requests (brand-scoped for approvers)
POST /approvals                  — create a typed, entity-linked change request
POST /approvals/{id}/approve     — approve; ENACTS the linked change (E2E-07)
POST /approvals/{id}/reject      — reject (comment required)

Enactment (E2E-07): a request may name the exact row it changes via
entity_type + entity_id. On approve, proposed_value is applied to that row by
_enact_approval(). Requests with no entity_type are advisory — the decision is
recorded and the submitter notified, but nothing is auto-applied.

Scope (E2E-04): each request carries a brand_group (derived server-side from the
linked entity at create time). Restricted approvers only see/decide requests in
their own group; NULL brand_group (legacy/unscoped) stays visible to all.

All linkage/scope columns come from migration 003. Every access is defensive so
the module keeps working if that migration has not been applied yet.
"""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import settings
from dependencies import _UNRESTRICTED_GROUPS, brand_to_group, require_auth
from models.auth import UserContext
from services.bq import BQClient
from services.push import send_push

router = APIRouter(prefix="/approvals", tags=["approvals"])

SFA_WEB = f"`{settings.bq_project}.{settings.bq_dataset}`"

APPROVER_ROLES = {"asm", "dm", "ho_admin"}
SUBMITTER_ROLES = {"spv", "asm", "ho_admin"}

# Entity types the engine knows how to apply on approve. Anything else is advisory.
ENACTABLE_TYPES = {"spv_target", "outlet_tier"}


class DecisionBody(BaseModel):
    comment: str = ""


class ApprovalCreate(BaseModel):
    type: str                         # domain tag, e.g. 'target_adjust' | 'tier_override'
    title: str
    proposed_value: str
    current_value: str | None = None
    reason: str = ""
    entity_type: str | None = None    # enactable: 'spv_target' | 'outlet_tier' (None = advisory)
    entity_id: str | None = None      # the row proposed_value applies to
    field_name: str | None = None     # informational: which field changes


def _is_unrestricted(user: UserContext) -> bool:
    return (
        user.role in ("ho_admin", "dm")
        or not user.brand_group
        or user.brand_group in _UNRESTRICTED_GROUPS
    )


def _assert_can_decide(user: UserContext, req_brand_group: str | None) -> None:
    """E2E-04: a restricted approver may only decide requests in their own brand
    group. NULL brand_group (legacy/unscoped) is decidable by anyone."""
    if _is_unrestricted(user):
        return
    if req_brand_group is not None and req_brand_group != user.brand_group:
        raise HTTPException(status_code=403, detail="Permintaan ini di luar cakupan brand Anda")


def _fetch_link(bq: BQClient, approval_id: str) -> dict:
    """Best-effort read of migration-003 linkage columns. Returns {} pre-migration."""
    try:
        row = bq.query_one(
            f"""SELECT entity_type, entity_id, field_name, brand_group, proposed_value
                FROM {SFA_WEB}.approval_request
                WHERE approval_id = @id AND is_deleted = FALSE""",
            [bq.p("id", "STRING", approval_id)],
        )
        return row or {}
    except Exception:
        return {}  # columns not present yet — treat as advisory/unscoped


@router.get("")
def list_approvals(
    status: str = Query("pending"),
    current_user: UserContext = Depends(require_auth),
):
    bq = BQClient.get()

    is_approver = current_user.role in APPROVER_ROLES
    restricted = is_approver and not _is_unrestricted(current_user)
    scope_suffix = (
        (f"all:{current_user.brand_group}" if restricted else "all")
        if is_approver else current_user.username
    )
    cache_key = f"approvals:{status}:{scope_suffix}"
    cached = bq.cache.get(cache_key)
    if cached is not None:
        return cached

    status_clause = (
        "AND ar.status = 'pending'"
        if status == "pending"
        else "AND ar.status IN ('approved','rejected','revision')"
    )
    submitter_clause = "" if is_approver else "AND ar.submitted_by = @submitter"
    scope_clause = "AND (ar.brand_group = @bg OR ar.brand_group IS NULL)" if restricted else ""

    params: list = []
    if not is_approver:
        params.append(bq.p("submitter", "STRING", current_user.username))
    if restricted:
        params.append(bq.p("bg", "STRING", current_user.brand_group))

    def _run(select_cols: str, with_scope: bool) -> list[dict]:
        clauses = f"ar.is_deleted = FALSE {status_clause} {submitter_clause}"
        if with_scope:
            clauses += f" {scope_clause}"
        return bq.query(
            f"SELECT {select_cols} FROM {SFA_WEB}.approval_request ar "
            f"WHERE {clauses} ORDER BY ar.submitted_at DESC LIMIT 100",
            params,
        )

    base_cols = (
        "ar.approval_id, ar.type, ar.title, ar.submitted_by, ar.submitted_at, "
        "ar.current_value, ar.proposed_value, ar.reason, ar.status, ar.comments_json"
    )
    try:
        rows = _run(base_cols + ", ar.entity_type, ar.brand_group", restricted)
    except Exception:
        # pre-migration: no linkage/scope columns — fall back to the legacy shape.
        rows = _run(base_cols, with_scope=False)

    result = []
    for r in rows:
        comments = []
        if r.get("comments_json"):
            try:
                comments = json.loads(r["comments_json"])
            except Exception:
                comments = []
        result.append({
            "approval_id":    r["approval_id"],
            "type":           r["type"],
            "title":          r["title"],
            "submitted_by":   r["submitted_by"],
            "submitted_at":   str(r["submitted_at"]),
            "current_value":  r.get("current_value"),
            "proposed_value": r["proposed_value"],
            "reason":         r["reason"],
            "status":         r["status"],
            "entity_type":    r.get("entity_type"),
            "brand_group":    r.get("brand_group"),
            "enactable":      (r.get("entity_type") or None) in ENACTABLE_TYPES,
            "sla_hours":      48,
            "comments":       comments,
        })
    bq.cache.set(cache_key, result, ttl=30)  # 30s — workflow queue, near real-time
    return result


@router.post("", status_code=201)
def create_approval(body: ApprovalCreate, current_user: UserContext = Depends(require_auth)):
    """Create a typed change request. For enactable types the linked entity is
    validated and its brand_group is derived server-side (never trusted from the
    client), so scope and enactment are trustworthy."""
    if current_user.role not in SUBMITTER_ROLES:
        raise HTTPException(status_code=403, detail="Anda tidak berhak mengajukan permintaan")

    bq = BQClient.get()
    entity_type = (body.entity_type or "").strip() or None
    brand_group: str | None = None

    if entity_type == "spv_target":
        if not body.entity_id:
            raise HTTPException(status_code=422, detail="entity_id wajib untuk spv_target")
        row = bq.query_one(
            f"""SELECT sm.brand_group AS brand_group
                FROM {SFA_WEB}.spv_target t
                JOIN {SFA_WEB}.dim_salesman sm USING (salesman_sk)
                WHERE t.spv_target_id = @id AND t.is_deleted = FALSE LIMIT 1""",
            [bq.p("id", "STRING", body.entity_id)],
        )
        if not row:
            raise HTTPException(status_code=404, detail="spv_target tidak ditemukan")
        brand_group = row.get("brand_group")
        # proposed_value must be a number we can apply later — validate now.
        _coerce_amount(body.proposed_value)
    elif entity_type == "outlet_tier":
        if not body.entity_id:
            raise HTTPException(status_code=422, detail="entity_id wajib untuk outlet_tier")
        row = bq.query_one(
            f"SELECT brand FROM {SFA_WEB}.dim_outlet WHERE CAST(outlet_sk AS STRING) = @id LIMIT 1",
            [bq.p("id", "STRING", body.entity_id)],
        )
        if not row:
            raise HTTPException(status_code=404, detail="Outlet tidak ditemukan")
        brand_group = brand_to_group(row.get("brand"))
    elif entity_type is not None:
        raise HTTPException(status_code=422, detail=f"entity_type '{entity_type}' tidak dikenal")

    # Advisory (no entity) requests inherit the submitter's brand group for scoping.
    if brand_group is None and not _is_unrestricted(current_user):
        brand_group = current_user.brand_group
    # A restricted submitter cannot file a request outside their own brand group.
    if not _is_unrestricted(current_user) and brand_group and brand_group != current_user.brand_group:
        raise HTTPException(status_code=403, detail="Tidak dapat mengajukan permintaan di luar brand Anda")

    approval_id = f"APR-{uuid.uuid4().hex[:16].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    linked_params = [
        bq.p("id", "STRING", approval_id), bq.p("tp", "STRING", body.type),
        bq.p("title", "STRING", body.title), bq.p("by", "STRING", current_user.username),
        bq.p("now", "TIMESTAMP", now), bq.p("cur", "STRING", body.current_value),
        bq.p("prop", "STRING", body.proposed_value), bq.p("reason", "STRING", body.reason),
        bq.p("et", "STRING", entity_type), bq.p("eid", "STRING", body.entity_id),
        bq.p("fn", "STRING", body.field_name), bq.p("bg", "STRING", brand_group),
    ]
    try:
        bq.execute(
            f"""INSERT INTO {SFA_WEB}.approval_request
                (approval_id, type, title, submitted_by, submitted_at, current_value,
                 proposed_value, reason, status, comments_json, is_deleted,
                 entity_type, entity_id, field_name, brand_group)
                VALUES (@id, @tp, @title, @by, @now, @cur, @prop, @reason, 'pending', '[]', FALSE,
                        @et, @eid, @fn, @bg)""",
            linked_params,
        )
    except Exception:
        # pre-migration: linkage columns absent — store the base request (advisory).
        bq.execute(
            f"""INSERT INTO {SFA_WEB}.approval_request
                (approval_id, type, title, submitted_by, submitted_at, current_value,
                 proposed_value, reason, status, comments_json, is_deleted)
                VALUES (@id, @tp, @title, @by, @now, @cur, @prop, @reason, 'pending', '[]', FALSE)""",
            linked_params[:8],
        )
        entity_type = None
    bq.cache.invalidate("approvals:")
    return {
        "approval_id": approval_id, "status": "pending",
        "entity_type": entity_type, "brand_group": brand_group,
        "enactable": entity_type in ENACTABLE_TYPES,
    }


def _coerce_amount(value) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="proposed_value harus berupa angka untuk spv_target")


def _validate_enactable(link: dict) -> None:
    """Pre-flight the linked value so enactment can't fail after we've claimed the
    request (E2E-13). Currently only spv_target needs a numeric check."""
    if (link.get("entity_type") or "") == "spv_target" and link.get("entity_id"):
        _coerce_amount(link.get("proposed_value"))


def _enact_approval(bq: BQClient, link: dict, now: str) -> bool:
    """Apply proposed_value to the linked row. Returns True if a change was applied,
    False for advisory/legacy requests. Raises on a bad value so the caller can
    abort BEFORE marking the request approved (no 'approved but not applied')."""
    entity_type = (link.get("entity_type") or "").strip()
    entity_id = link.get("entity_id")
    proposed = link.get("proposed_value")
    if entity_type not in ENACTABLE_TYPES or not entity_id:
        return False

    if entity_type == "spv_target":
        amount = _coerce_amount(proposed)
        bq.execute(
            f"""UPDATE {SFA_WEB}.spv_target
                SET spv_target = @val, approval_status = 'approved', updated_at = @now
                WHERE spv_target_id = @id AND is_deleted = FALSE""",
            [bq.p("val", "FLOAT64", amount), bq.p("now", "TIMESTAMP", now), bq.p("id", "STRING", entity_id)],
        )
        bq.cache.invalidate("target:")
        bq.cache.invalidate("dashboard:comply:")
        return True

    if entity_type == "outlet_tier":
        bq.execute(
            f"UPDATE {SFA_WEB}.dim_outlet SET store_grade = @val WHERE CAST(outlet_sk AS STRING) = @id",
            [bq.p("val", "STRING", str(proposed)), bq.p("id", "STRING", entity_id)],
        )
        bq.cache.invalidate("store360:")
        return True

    return False


def _update_approval(approval_id: str, decision: str, comment: str, user: UserContext):
    bq = BQClient.get()
    row = bq.query_one(
        f"SELECT status, comments_json, submitted_by FROM {SFA_WEB}.approval_request WHERE approval_id = @id AND is_deleted = FALSE",
        [bq.p("id", "STRING", approval_id)],
    )
    if not row:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="Request is no longer pending")

    link = _fetch_link(bq, approval_id)
    _assert_can_decide(user, link.get("brand_group"))

    now = datetime.now(timezone.utc).isoformat()

    # Pre-validate the enactable value so the apply step (after we claim the
    # request below) cannot fail on bad data and leave it approved-but-not-applied.
    if decision == "approve":
        _validate_enactable(link)

    comments = []
    if row.get("comments_json"):
        try:
            comments = json.loads(row["comments_json"])
        except Exception:
            pass
    if comment:
        comments.append({
            "author":     user.username,
            "role":       user.role,
            "body":       comment,
            "created_at": now,
        })

    status_map = {"approve": "approved", "reject": "rejected", "revise": "revision"}
    new_status = status_map[decision]

    # E2E-13: atomically CLAIM the request (pending → decided). If another approver
    # already decided it, we affect 0 rows and abort BEFORE enacting — so a lost
    # approve/reject race can neither double-apply nor leave the entity changed
    # while the request shows a different decision.
    affected = bq.execute_dml(
        f"""
        UPDATE {SFA_WEB}.approval_request
        SET status = @status, decided_by = @decider, decided_at = @now, comments_json = @cjson
        WHERE approval_id = @id AND status = 'pending'
        """,
        [
            bq.p("status",  "STRING",    new_status),
            bq.p("decider", "STRING",    user.username),
            bq.p("now",     "TIMESTAMP", now),
            bq.p("cjson",   "STRING",    json.dumps(comments)),
            bq.p("id",      "STRING",    approval_id),
        ],
    )
    if affected == 0:
        raise HTTPException(status_code=409, detail="Permintaan sudah diproses oleh approver lain.")

    # Now that we exclusively own the decision, apply the linked change.
    applied = _enact_approval(bq, link, now) if decision == "approve" else False
    bq.cache.invalidate("approvals:")

    # Push notification to the original submitter
    submitter_row = bq.query_one(
        f"SELECT push_token FROM {SFA_WEB}.users WHERE username = @uname AND push_token IS NOT NULL",
        [bq.p("uname", "STRING", row.get("submitted_by", ""))],
    )
    if submitter_row and submitter_row.get("push_token"):
        verb = "disetujui" if decision == "approve" else "ditolak"
        send_push(
            submitter_row["push_token"],
            title=f"Approval {verb.capitalize()}",
            body=f"Permintaan Anda telah {verb}." + (f" Catatan: {comment}" if comment else ""),
            data={"type": "approval_decision", "approval_id": approval_id, "status": new_status},
        )

    return {"message": f"Request {new_status}.", "applied": applied}


@router.post("/{approval_id}/approve")
def approve(approval_id: str, body: DecisionBody, current_user: UserContext = Depends(require_auth)):
    if current_user.role not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return _update_approval(approval_id, "approve", body.comment, current_user)


@router.post("/{approval_id}/reject")
def reject(approval_id: str, body: DecisionBody, current_user: UserContext = Depends(require_auth)):
    if current_user.role not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if not body.comment:
        raise HTTPException(status_code=400, detail="Comment required for rejection")
    return _update_approval(approval_id, "reject", body.comment, current_user)


@router.post("/{approval_id}/revise")
def revise(approval_id: str, body: DecisionBody, current_user: UserContext = Depends(require_auth)):
    """E2E-28: send a request back to the submitter for revision (status 'revision').
    Applies nothing; a comment explaining what to change is required."""
    if current_user.role not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if not body.comment:
        raise HTTPException(status_code=400, detail="Comment required to request a revision")
    return _update_approval(approval_id, "revise", body.comment, current_user)
