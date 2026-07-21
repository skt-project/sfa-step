# ADR-0001 — BigQuery as the transactional store

**Status:** Accepted (retroactive record) · **Date:** 2026-07-21
**Deciders:** STEP engineering · **Supersedes design note:** [04-database-erd](../04-database-erd.md) (which recommended a Postgres OLTP tier)

## Context

STEP's operational writes — visit check-in/checkout/submit, approvals, targets,
announcements, notifications — are persisted directly to **Google BigQuery**
(`sfa_web` dataset). The original design ([04-database-erd](../04-database-erd.md))
recommended a **Postgres OLTP** tier for transactional work with BigQuery reserved
for analytics. The as-built system did not adopt Postgres; BigQuery is both the
system of record and the analytics store.

This ADR records the decision, its consequences, and the conditions under which it
should be revisited — so the trade-off is deliberate rather than accidental.

## Decision

Use **BigQuery as the transactional store** for STEP, mitigating its OLTP
limitations in the application layer rather than introducing a second database.

## Rationale

- **Single source of truth / zero ETL.** Field data is analytics-adjacent; keeping
  it in BigQuery removes an OLTP→warehouse sync and its lag/duplication class of bugs.
- **Operational simplicity.** One managed store, one credential path (workload
  identity on Cloud Run), no connection-pool/HA/patching burden of a Postgres tier.
- **Scale headroom for reads.** Dashboards and reports over large history are BQ's
  strength and dominate the read workload.

## Consequences (and their mitigations)

| Limitation of BQ as OLTP | Mitigation in place |
|---|---|
| No row-level transactions; DML jobs take ~1–3 s | Endpoints are **idempotent** (check-in dedupes by `schedule_id`; submit short-circuits when already `SUBMITTED`); mobile persists `server_visit_id` immediately after check-in to avoid duplicate replays. |
| No FK/unique constraints (referential integrity) | Enforced in the application layer (`dependencies.py`, routers); source datasets are read-only. |
| Per-row update latency / no hot-row updates | In-process TTL cache for reference data (`services/bq.py`); batched DML where hot. |
| Concurrency (last-write-wins) | Writes scoped to `sfa_web`; conflict surface is small (single field user per visit). |
| Cost per query/DML | Monitor slot usage + DML latency; keep source datasets read-only. |

## Revisit triggers

Re-open this decision (evaluate a Postgres/Cloud SQL OLTP tier fronting BigQuery) if
**any** of the following holds:

1. Submit-visit **p95 latency > 3 s** sustained (already the runbook's alert
   threshold — see [06-operations-runbook](06-operations-runbook.md)).
2. Concurrent-write conflicts become user-visible (lost updates on approvals/targets).
3. DML cost on hot tables (`step_visit_item`) grows non-linearly with active users.
4. A feature requires true multi-row transactional integrity.

## Status notes

Recorded as finding **F-09** in the [production readiness audit](10-production-readiness-audit.md).
This is an *accepted, monitored* risk for the current scale — not a "do nothing":
the p95 trigger above is the concrete guardrail.
