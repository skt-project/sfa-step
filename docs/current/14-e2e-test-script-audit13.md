# 14 — E2E Test Script for the Audit-13 Fix Branches

**Branches under test:** `sfa-step @ fix/authz-consistency-audit13`, `sfa-mobile @ fix/sync-issues`
**Precondition:** migrations `003_approval_linkage.sql` + `004_token_version.sql` applied to `sfa_web` ✅

> ⚠️ **Test the branch, not production.** The Vercel web app and the Cloud Run API still run the OLD code. To validate these fixes, run the branch locally (below) or deploy it to a staging Cloud Run revision first. The migrations are additive/backward-compatible, so they don't affect the live app until the new code is deployed.

---

## 0. Credentials (UAT — seeded defaults, rotate before real go-live)

| Username | Password | Role / BU | Use for |
|---|---|---|---|
| `admin` | `Step@2026!` | ho_admin (unrestricted) | approver, admin, cross-brand reads |
| `test_spv` | `STEP@2026` | spv / SKT (unmapped → BU-wide) | submitter, SPV actions |
| `test_dist` | `STEP@2026` | dm | distributor approvals |
| `test_se` | `STEP@2026` | salesman / SKT (linked `salesman_sk`) | visit lifecycle, IDOR |
| `demo` | `STEP@2026` | salesman / SKT | second SE (ownership tests) |

(Source: `backend/rotated-credentials.local.txt`, `docs/current/06-operations-runbook.md`.)

---

## 1. Run the branch locally

```bash
# ── Backend (terminal 1) ─────────────────────────────────────
cd D:/GitHub/sfa-step/backend
#  .env must have JWT_SECRET + BQ creds (BQ_SA_KEY_PATH=... or ADC). You already run this.
uvicorn main:app --reload --port 8000
#  → http://localhost:8000/health should return {"status":"ok",...}

# ── Web (terminal 2) ─────────────────────────────────────────
cd D:/GitHub/sfa-step/frontend
#  point the web app at the LOCAL api:
echo 'VITE_API_BASE_URL=http://localhost:8000/api/v1' > .env.local
npm run dev            # → http://localhost:5173 (or shown port)

# ── Mobile (terminal 3, optional) ────────────────────────────
cd D:/GitHub/sfa-mobile
#  use your machine's LAN IP so the phone can reach the API:
EXPO_PUBLIC_API_BASE_URL=http://<YOUR_LAN_IP>:8000/api/v1 npx expo start
```

**API base for all curl below:** `http://localhost:8000/api/v1`

---

## 2. API smoke script (bash) — fastest way to verify backend fixes

```bash
API=http://localhost:8000/api/v1

login () { # login <user> <pass> -> prints token
  curl -s -X POST "$API/auth/login" -H 'Content-Type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}

ADMIN=$(login admin 'Step@2026!')
SPV=$(login test_spv 'STEP@2026')
SE=$(login test_se 'STEP@2026')
echo "tokens acquired"
```

### T1 — Session revocation (E2E-14) ✅ headline security fix
```bash
# me works with a fresh token
curl -s -o /dev/null -w "me before logout: %{http_code}\n" "$API/auth/me" -H "Authorization: Bearer $SE"
# log out (server bumps token_version)
curl -s -o /dev/null -w "logout: %{http_code}\n" -X POST "$API/auth/logout" -H "Authorization: Bearer $SE"
# reuse the SAME token → must now be 401 (was 200 before the fix)
curl -s -o /dev/null -w "me after logout (expect 401): %{http_code}\n" "$API/auth/me" -H "Authorization: Bearer $SE"
SE=$(login test_se 'STEP@2026')   # re-login for later tests
```
**Expect:** `200`, `200`, **`401`**.

### T2 — Check-in cannot spoof salesman / cannot future-date (E2E-02)
```bash
TODAY=$(date +%F)
# SE tries to check in AS ANOTHER salesman_sk → server forces it to the token's own sk
curl -s -X POST "$API/visit/checkin" -H "Authorization: Bearer $SE" -H 'Content-Type: application/json' \
  -d "{\"salesman_sk\":\"SOMEONE-ELSE-SK\",\"outlet_sk\":\"1\",\"visit_date\":\"$TODAY\"}" | python -m json.tool
# → note the returned visit_id, then GET it and confirm salesman_sk == test_se's own sk (from /auth/me), NOT "SOMEONE-ELSE-SK"

# future-dated check-in → 422
curl -s -o /dev/null -w "future date (expect 422): %{http_code}\n" -X POST "$API/visit/checkin" \
  -H "Authorization: Bearer $SE" -H 'Content-Type: application/json' \
  -d "{\"salesman_sk\":\"x\",\"outlet_sk\":\"1\",\"visit_date\":\"2030-01-01\"}"
```

### T3 — Negative qty / price rejected (E2E-10)
```bash
# reuse a real visit_id from T2 (call it VID)
curl -s -o /dev/null -w "negative qty (expect 422): %{http_code}\n" -X POST "$API/visit/$VID/submit" \
  -H "Authorization: Bearer $SE" -H 'Content-Type: application/json' \
  -d '{"items":[{"sku_id":"X","qty":-5,"stp":1000}]}'
```

### T4 — Cross-brand detail scoping (E2E-03)
```bash
# admin lists salesmen, find one whose brand_group = "G2G"
curl -s "$API/salesman/list?limit=200" -H "Authorization: Bearer $ADMIN" \
  | python -c 'import sys,json;[print(r["salesman_sk"],r.get("brand_group")) for r in json.load(sys.stdin)["items"] if r.get("brand_group")=="G2G"][:5]'
# take one G2G salesman_sk (call it G2G_SK). test_spv is SKT:
curl -s -o /dev/null -w "SKT user opens G2G 360 (expect 404): %{http_code}\n" "$API/salesman/360/$G2G_SK" -H "Authorization: Bearer $SPV"
# and an SKT salesman → 200
```

### T5 — Approval create → approve → **enact** (E2E-07) ✅ Critical fix
```bash
PERIOD=$(date +%Y-%m-01)
# 1) find an SKT spv_target row id + its current amount
curl -s "$API/target/spv?brand=Skintific&period_month=$PERIOD" -H "Authorization: Bearer $ADMIN" \
  | python -c 'import sys,json;r=json.load(sys.stdin)["rows"][0];print("ID=",r["spv_target_id"]," NOW=",r["spv_target"])'
# set TID=<spv_target_id> from above, then:
# 2) SPV files a linked change request (proposed 12345)
APR=$(curl -s -X POST "$API/approvals" -H "Authorization: Bearer $SPV" -H 'Content-Type: application/json' \
  -d "{\"type\":\"target_adjust\",\"title\":\"Test adjust\",\"entity_type\":\"spv_target\",\"entity_id\":\"$TID\",\"field_name\":\"spv_target\",\"proposed_value\":\"12345\",\"reason\":\"e2e\"}" \
  | python -c 'import sys,json;d=json.load(sys.stdin);print(d["approval_id"]);import sys;sys.stderr.write(str(d))')
# 3) admin approves → response should include "applied": true
curl -s -X POST "$API/approvals/$APR/approve" -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{"comment":"ok"}' | python -m json.tool
# 4) verify the target actually changed to 12345 and approval_status='approved'
curl -s "$API/target/spv?brand=Skintific&period_month=$PERIOD" -H "Authorization: Bearer $ADMIN" \
  | python -c "import sys,json;[print(r['spv_target'],r['approval_status']) for r in json.load(sys.stdin)['rows'] if r['spv_target_id']=='$TID']"
```
**Expect:** approve returns `"applied": true`; the row now reads `12345 approved`.

### T6 — Approval race / no double-decide (E2E-13)
```bash
# approving the SAME request again must fail (already decided)
curl -s -o /dev/null -w "second approve (expect 400/409): %{http_code}\n" -X POST "$API/approvals/$APR/approve" \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{"comment":"again"}'
```

### T7 — Revise action (E2E-28)
```bash
# create another request, then revise it
# ... POST /approvals like T5 → APR2, then:
curl -s -X POST "$API/approvals/$APR2/revise" -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{"comment":"please adjust"}' | python -m json.tool
# GET /approvals?status=history → the item shows status "revision"
```

### T8 — Out-of-scope approve blocked (E2E-04)
```bash
# a G2G-scoped approver approving an SKT-linked request → 403 (needs a G2G asm/dm account to fully exercise)
```

### T9 — Outlet assign validation (E2E-29)
```bash
curl -s -o /dev/null -w "non-numeric sk (expect 422): %{http_code}\n" -X POST "$API/outlet/assign" \
  -H "Authorization: Bearer $ADMIN" -H 'Content-Type: application/json' -d '{"outlet_id":"1","salesman_sk":"abc"}'
```

### T10 — Import guards (E2E-15/31)
```bash
# wrong extension → 422
printf 'a,b\n1,2\n' > /tmp/x.txt
curl -s -o /dev/null -w "non-csv (expect 422): %{http_code}\n" -X POST "$API/import/salesman" \
  -H "Authorization: Bearer $ADMIN" -F 'file=@/tmp/x.txt'
```

---

## 3. Full-lifecycle consistency test (E2E-06) — do this one via API or UI

The most important data-consistency fix: an SPV final-qty adjustment must flow into `total_demand` everywhere.

1. As `test_se`: check-in → checkout → submit a visit with items (e.g. qty 10 × stp 1000 = 10,000). Record the `visit_id`.
2. `GET /visit/{id}` → note `total_demand` = 10,000.
3. As `test_spv`: `PUT /visit/{id}/final-qty` with `{"items":[{"sku_id":"...","final_qty":4}]}`.
4. `GET /visit/{id}` → `total_demand` should now be **4,000** (was stuck at 10,000 before the fix), and the PDF (`GET /visit/{id}/pdf`) total matches.
5. `GET /salesman/360/{se_sk}` and the Dashboard → sell-in reflects **4,000**, not 10,000.

---

## 4. Web UI walkthrough (http://localhost:5173)

| # | Steps | Expect |
|---|---|---|
| W1 | Login `admin` → click **Logout** → try Back/refresh | Redirected to Login; old session dead (T1). |
| W2 | Login `admin` → **Approvals** → open the T5 request → **Setujui** | Toast "disetujui & perubahan diterapkan"; Target Management shows the new value. |
| W3 | Approvals → open a pending request → **Minta Revisi** (needs comment) | Moves to History as "Revisi". |
| W4 | Approvals → two browser tabs, approve same item in both | One succeeds; the other toasts the 409 reason. |
| W5 | Login `test_spv` (SKT) → open a G2G store in **Store 360** by URL | 404 / not found (brand scope). |

---

## 5. Mobile walkthrough (Expo)

| # | Steps | Expect |
|---|---|---|
| M1 | Login `test_se` → enable Airplane mode → force-quit → relaunch | Still logged in (session restored offline, E2E-25) — not stranded at Login. |
| M2 | Offline: complete a visit (check-in→survey→checkout→"SELESAI") → back online → pull-to-refresh | Syncs once, no duplicate visit. |
| M3 | Record a visit; compare the Rupiah total shown vs the web/PDF total for the same visit | Identical to the rupiah (rounding parity, E2E-33). |
| M4 | Login → Logout → try any action | Forced back to Login; token revoked server-side. |

---

## 6. Known-not-yet-wired (so you don't file it as a bug)
- The **Target Management "Request Change" button** (files a linked approval from the UI) is still being wired — for now create linked requests via the T5 curl. Everything else in the approval loop (approve/reject/revise + enactment) is fully testable from the UI.
- Deferred-by-design items are listed in `13-ecosystem-e2e-audit.md` §Remediation status (GPS geofence, cache coherence, dataset convergence, etc.).
