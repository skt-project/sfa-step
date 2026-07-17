# STEP Web — Windows Server Deployment Guide (Netlify → On-Prem)

**Audience:** IT/DevOps deploying STEP Web on a company Windows Server.
**Scope:** Move STEP Web (the Vite/React static build) off Netlify onto a physical Windows Server, publicly accessible, with HTTPS. Backend (FastAPI) options included.
**Current baseline:**
- **Web frontend:** Vite + React 18 static build (`frontend/dist/`), currently on Netlify.
- **Backend API:** FastAPI, **already deployed on Google Cloud Run** at `https://step-api-141828905128.asia-southeast1.run.app` — the mobile app also depends on this exact URL.
- **Data:** Google BigQuery (`skintific-data-warehouse.sfa_web`). Reached via the backend only; the browser never talks to BigQuery.

> **Key decision up front:** You can move *just the frontend* (lowest risk — backend stays on Cloud Run, mobile keeps working unchanged) or *both frontend + backend*. This guide defaults to **frontend-only on Windows, backend stays on Cloud Run**, and includes a full "also host the backend" appendix. Moving the backend means the mobile app's hardcoded API URL must change and a new APK must ship — treat that as a separate, higher-risk project.

---

## 1. Recommended production architecture

**Option A — Frontend-only on Windows (RECOMMENDED)**
```
                    Internet
                       │
             Cloudflare (DNS + TLS + Tunnel)
                       │
        ┌──────────────┴───────────────┐
        │      Windows Server           │
        │  ┌─────────────────────────┐  │
        │  │ Nginx (or IIS)          │  │   serves frontend/dist (static)
        │  │  :443  step.company.com │  │   + reverse-proxies /api → Cloud Run
        │  └─────────────────────────┘  │
        └───────────────────────────────┘
                       │  /api/*
                       ▼
        Google Cloud Run  (FastAPI backend — unchanged)
                       │
                       ▼
              Google BigQuery (sfa_web)
```
- The Windows box serves static files and (optionally) proxies `/api` to Cloud Run so the browser sees a single origin (no CORS headaches).
- Mobile app untouched — it keeps calling Cloud Run directly.

**Option B — Frontend + Backend on Windows** (see Appendix A): the Windows box also runs `uvicorn` as a Windows Service and holds the BigQuery service-account key. Higher operational burden; requires a new mobile APK pointing at the new API host.

---

## 2. IIS vs Nginx — recommendation

| Factor | **Nginx for Windows** | IIS |
|---|---|---|
| SPA fallback (`try_files … /index.html`) | one line | needs URL Rewrite module + web.config |
| Reverse proxy to Cloud Run | `proxy_pass`, trivial | ARR + URL Rewrite, heavier |
| Config as code (versionable) | single `nginx.conf` | XML in IIS manager/appcmd |
| Familiarity on Windows shops | lower | higher |
| TLS via Cloudflare origin cert | easy | easy |

**Recommendation: Nginx** for its one-file, version-controllable config and trivial SPA + proxy setup. **Choose IIS only if** your org mandates it or you already run other IIS sites on the box. Both are fully documented below (Nginx primary, IIS in Appendix B).

---

## 3. Docker vs non-Docker — recommendation

**Recommendation: non-Docker (native Nginx service).** Rationale:
- The frontend is just static files — Docker adds a daemon, image lifecycle, and Windows-container quirks for zero benefit here.
- Native Nginx-as-a-service starts in ms, auto-restarts via Windows Service Manager, and is trivial to update (drop new `dist/`, reload).
- **Use Docker only if** you also host the backend on Windows AND already run Docker Desktop/EE there — then a `docker compose` with `nginx` + `uvicorn` is reasonable (Appendix A shows both).

---

## 4. Public access configuration — two paths

**Path 1 — Cloudflare Tunnel (RECOMMENDED when there is no static public IP).** No inbound firewall ports, no port-forwarding, works behind NAT/CGNAT. See §7.

**Path 2 — Direct public IP + port-forward.** If the server has a routable public IP or your network admin can forward TCP 443 (and 80 for ACME) to it, use Let's Encrypt (§6). Requires opening firewall ports (§8).

---

## 5. Domain configuration

1. Pick a hostname, e.g. `step.skintific.com` (or a subdomain your DNS admin controls).
2. **With Cloudflare Tunnel (§7):** the tunnel creates the DNS record for you (a proxied CNAME). No A record needed.
3. **With direct IP:** create an `A` record `step.skintific.com → <server public IP>`, proxied through Cloudflare (orange cloud) for TLS + DDoS, or grey-cloud if you terminate TLS yourself with Let's Encrypt.
4. Set the SPA to be origin-agnostic: the app already reads `VITE_API_BASE_URL` at build time (see §9), so the domain only affects where the site is served, not the API.

---

## 6. HTTPS with Let's Encrypt (direct-IP path)

Use **win-acme** (`wacs.exe`), the standard Windows ACME client.

```powershell
# Download win-acme from https://www.win-acme.com/ and unzip to C:\win-acme
cd C:\win-acme
.\wacs.exe
# Choose: N (new cert) → manual/host → step.skintific.com
# Validation: http-01 (needs port 80 open) OR dns-01 via Cloudflare plugin
# Store: PEM files to C:\nginx\ssl\  (point nginx at fullchain.pem + key.pem)
```
- win-acme installs a **scheduled task** that auto-renews every 60 days and can run a post-hook to `nginx -s reload`.
- If using Cloudflare proxy (orange cloud), you can instead use a **Cloudflare Origin Certificate** (15-year validity, §7.4) and skip Let's Encrypt entirely.

---

## 7. Cloudflare Tunnel (recommended — no public IP required)

### 7.1 Install
```powershell
# Install cloudflared as a service
winget install --id Cloudflare.cloudflared
# or download cloudflared-windows-amd64.exe → rename cloudflared.exe → C:\cloudflared\
```
### 7.2 Authenticate + create tunnel
```powershell
cloudflared tunnel login                      # opens browser, pick the zone (skintific.com)
cloudflared tunnel create step-web            # prints a Tunnel UUID + creates creds json
cloudflared tunnel route dns step-web step.skintific.com
```
### 7.3 Config `C:\Users\<user>\.cloudflared\config.yml`
```yaml
tunnel: step-web
credentials-file: C:\Users\<user>\.cloudflared\<TUNNEL-UUID>.json
ingress:
  - hostname: step.skintific.com
    service: http://localhost:8080        # local Nginx serving the SPA
  - service: http_status:404
```
### 7.4 Run as a Windows service (auto-start)
```powershell
cloudflared service install
Start-Service cloudflared
```
Now `https://step.skintific.com` is public, TLS terminated by Cloudflare, no inbound ports opened. Nginx only needs to listen on `localhost:8080`.

---

## 8. Firewall configuration

**With Cloudflare Tunnel:** **no inbound rules needed** — the tunnel makes only outbound connections. Keep the box locked down:
```powershell
# Nginx binds localhost only; nothing inbound required. Verify no stray listeners:
Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 80,443,8080
```
**With direct IP path:** open only 443 (and 80 for ACME renewals):
```powershell
New-NetFirewallRule -DisplayName "STEP HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
New-NetFirewallRule -DisplayName "STEP HTTP (ACME)" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
```
Never expose BigQuery keys or the uvicorn port publicly; if hosting the backend, keep it on `localhost` behind the reverse proxy.

---

## 9. Build & serve the frontend

### 9.1 Build (on a machine with Node 18+)
```powershell
cd frontend
# Point the SPA at the API. Option A (proxy via same origin): leave default & proxy /api in nginx.
# Option B (call Cloud Run directly): set the full URL.
"VITE_API_BASE_URL=/api/v1" | Out-File -Encoding utf8 .env.production
npm ci
npm run build          # outputs frontend/dist
```
> The app's API base is `import.meta.env.VITE_API_BASE_URL ?? <Cloud Run URL>` (see `frontend/src/api/client.ts`). Setting it to `/api/v1` makes the browser hit the same origin, and Nginx proxies to Cloud Run — cleanest for cookies/CORS.

### 9.2 Deploy the static files
Copy `frontend/dist` to `C:\step-web\dist` on the server.

### 9.3 Nginx config `C:\nginx\conf\nginx.conf` (SPA + API proxy)
```nginx
worker_processes auto;
events { worker_connections 1024; }
http {
  include       mime.types;
  default_type  application/octet-stream;
  sendfile      on;
  gzip on;
  gzip_types text/css application/javascript application/json image/svg+xml;

  server {
    listen 127.0.0.1:8080;         # Cloudflare Tunnel points here (or 443 for direct-IP + TLS)
    server_name step.skintific.com;
    root C:/step-web/dist;
    index index.html;

    # Long-cache fingerprinted assets, never cache index.html
    location /assets/ { expires 1y; add_header Cache-Control "public, immutable"; }
    location = /index.html { add_header Cache-Control "no-cache"; }

    # SPA fallback — every non-file route serves index.html
    location / { try_files $uri $uri/ /index.html; }

    # Reverse-proxy the API to Cloud Run (single-origin)
    location /api/ {
      proxy_pass https://step-api-141828905128.asia-southeast1.run.app/api/;
      proxy_set_header Host step-api-141828905128.asia-southeast1.run.app;
      proxy_ssl_server_name on;
      proxy_set_header X-Forwarded-For $remote_addr;
      proxy_read_timeout 60s;
    }
  }
}
```
Reload after any change: `C:\nginx\nginx.exe -s reload`.

---

## 10. Nginx as a Windows Service (auto-start on reboot)

Nginx has no native service wrapper — use **NSSM** (Non-Sucking Service Manager) or **WinSW**.
```powershell
# NSSM
choco install nssm -y            # or download from nssm.cc
nssm install STEPNginx C:\nginx\nginx.exe
nssm set STEPNginx AppDirectory C:\nginx
nssm set STEPNginx Start SERVICE_AUTO_START
nssm set STEPNginx AppStopMethodConsole 0        # use nginx -s stop for graceful stop
nssm start STEPNginx
```
Confirm it survives reboot: `Get-Service STEPNginx` → **Running / Automatic**. Do the same for `cloudflared` (§7.4 already installs it as a service).

---

## 11. Backup strategy

| Asset | What | How | Frequency |
|---|---|---|---|
| Frontend build | `C:\step-web\dist` | It's reproducible from git — back up the **git tag** instead (the source of truth). Keep the last 2–3 `dist` zips for instant rollback. | each deploy |
| Nginx/Cloudflared config | `nginx.conf`, `.cloudflared\config.yml`, tunnel creds JSON | Copy to a secured share + password manager (creds JSON is a secret). | on change |
| TLS certs | `C:\nginx\ssl\` or Cloudflare origin cert | win-acme auto-renews; export origin cert to vault. | on issue |
| **BigQuery data** | `sfa_web` dataset | **Not on this server.** Use BigQuery's built-in 7-day time-travel + scheduled table snapshots/exports to GCS (owned by the data team). | daily (GCS export) |
| Backend | Cloud Run revision | Cloud Run keeps prior revisions; roll back in console. | automatic |

Automate a per-deploy zip:
```powershell
Compress-Archive C:\step-web\dist "C:\step-web\backups\dist_$(Get-Date -f yyyyMMdd_HHmm).zip"
```

---

## 12. Monitoring & logging

- **Nginx access/error logs:** `C:\nginx\logs\`. Rotate with a scheduled task (`logrotate` equivalent: rename + `nginx -s reopen` daily).
- **Uptime:** Cloudflare Analytics (built-in) + a free external monitor (e.g. UptimeRobot) hitting `https://step.skintific.com` every 5 min.
- **Windows:** Task Scheduler health check that pings the site and writes to Event Log / alerts on failure.
- **Backend:** Google Cloud Run metrics + Cloud Logging (latency, 5xx, instance count) — already available in GCP console.
- **Synthetic check:** the API exposes `GET /health` → `{"status":"ok"}`. Monitor `https://step.skintific.com/api/../health` or the Cloud Run `/health` directly.

---

## 13. Rollback procedure

**Frontend (fast):**
```powershell
# 1. Stop serving new build, restore previous dist
Expand-Archive C:\step-web\backups\dist_<previous>.zip -DestinationPath C:\step-web\dist -Force
C:\nginx\nginx.exe -s reload
```
Or, git-based: `git checkout <previous-tag>`, `npm ci && npm run build`, redeploy `dist`.

**Backend:** Cloud Run → Revisions → “Manage traffic” → route 100% to the previous known-good revision (instant, no redeploy).

**Database migration (005 adjustment):** additive columns only (`ADD COLUMN IF NOT EXISTS`) — safe to leave in place; the backend degrades gracefully if absent, so no DB rollback is needed for a frontend/back rollback.

Keep a one-line **"last known good"** record (git tag + Cloud Run revision id) with every release so rollback is unambiguous.

---

## 14. Scaling for 200–300 concurrent users

**Frontend:** static files behind Cloudflare cache — 300 concurrent users is trivial; Cloudflare serves assets from edge. A single Windows Nginx easily handles the origin misses. No scaling action needed.

**Backend (the real constraint):**
- Cloud Run autoscales by concurrency. Set **min instances = 1** (avoid cold starts) and **max = 5–10**; concurrency ~40–80/instance. 300 users with think-time rarely exceed a few hundred req/min.
- **BigQuery is the bottleneck to watch,** not CPU: every visit/list/dashboard call is a BQ query (1–3 s latency, per-query cost). For 200–300 concurrent field users:
  - Lean on the backend's existing in-process TTL cache (`services/bq.py`) for reference/aggregate data; extend caching to dashboard/report endpoints.
  - Add **BI Engine** reservation or materialized views for hot dashboards.
  - Batch writes (the sprint already batched submit-item inserts) to cut DML round-trips.
  - Consider a read replica pattern: heavy analytics → scheduled tables; transactional reads → smaller curated tables.
- **If the backend also moves to Windows** (Appendix A): run **4–8 uvicorn/gunicorn workers** behind Nginx, and put the box behind a load balancer only if you add a second node. For 300 users a single 4-core/8 GB VM with 4 workers is comfortable, assuming BigQuery latency is managed.

**Recommended target state for 300 users:** frontend on Windows+Cloudflare (done here), backend staying on Cloud Run (autoscaling), BigQuery caching/materialization tuned. Revisit only if p95 API latency climbs above ~2 s.

---

## Appendix A — Also hosting the FastAPI backend on Windows

1. Install Python 3.13, create venv, `pip install -r backend/requirements.txt`.
2. Place the BigQuery service-account JSON **outside** web root (e.g. `C:\secrets\bq-sa.json`), set `BQ_SA_KEY_PATH` in `backend\.env`, plus `JWT_SECRET`, `CORS_ORIGINS=https://step.skintific.com`.
3. Run uvicorn behind Nginx as a service:
   ```powershell
   nssm install STEPapi C:\path\venv\Scripts\python.exe "-m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4"
   nssm set STEPapi AppDirectory C:\path\backend
   nssm set STEPapi Start SERVICE_AUTO_START
   nssm start STEPapi
   ```
4. Point Nginx `location /api/` at `http://127.0.0.1:8000/api/`.
5. **Mobile impact:** update `src/api/client.ts` `BASE_URL` to the new host, bump `versionCode`, rebuild + redistribute the APK. Do NOT skip this — the current APK is hardwired to the Cloud Run URL.

## Appendix B — IIS instead of Nginx
1. Install IIS + **URL Rewrite** + **Application Request Routing (ARR)**.
2. Create a site rooted at `C:\step-web\dist`, binding `step.skintific.com:443` (import Cloudflare origin cert or win-acme cert).
3. `web.config` SPA fallback + API proxy:
   ```xml
   <configuration><system.webServer><rewrite><rules>
     <rule name="API" stopProcessing="true">
       <match url="^api/(.*)" />
       <action type="Rewrite" url="https://step-api-141828905128.asia-southeast1.run.app/api/{R:1}" />
     </rule>
     <rule name="SPA" stopProcessing="true">
       <match url=".*" />
       <conditions><add input="{REQUEST_FILENAME}" matchType="IsFile" negate="true" /></conditions>
       <action type="Rewrite" url="/index.html" />
     </rule>
   </rules></rewrite></system.webServer></configuration>
   ```
4. Enable ARR proxy (`ARR → Server Proxy Settings → Enable proxy`).

---

**Go/No-Go for on-prem cutover:** keep Netlify live, deploy to Windows on a temporary hostname, run the §12 smoke checks + the E2E scripts against it, then flip DNS. Keep Netlify as instant fallback for 1–2 weeks before decommissioning.
