# 05 — Mobile App Guide (As-Built)

Repo: `D:\GitHub\sfa-mobile` (`github.com/skt-project/sfa-mobile`, branch `master`)
App: **Skintific SFA** · `com.skintific.sfa` · current release **v1.4.2 (versionCode 11)**

## Navigation map

Role from JWT decides the branch (`user.role === "spv"` → SPV, otherwise SE — legacy `se` role lands in the SE branch).

**SE tabs:** Home · Rute · Riwayat · Info (Announcements) · Profil
**SE stack:** RouteList → VisitCheckin → VisitSurvey (order entry) → VisitCheckout → (VisitHistory, VisitDetail, RevisionEdit, Notifications)
**SPV tabs:** Dashboard · Approval · Tim · Info · Profil
**SPV stack:** ApprovalQueue, TeamOverview, VisitDetail, Notifications

Key screen behaviors:
- **RouteList** — 5 visit states (Belum/Terlewat/Check-in/Checkout/Disubmit) + sync pill (🟡 Local / 🟢 Tersinkron). Tapping a `checked_out`/`submitted` store opens the **read-only** VisitDetail; only untouched stores enter Check-In; `checked_in` resumes via server idempotency. Skip flow batches "Terlewat" stores to the SPV.
- **VisitCheckin** — mandatory photo (camera; gallery on web build), GPS captured but informational.
- **VisitSurvey** — BU-filtered, priced-only SKUs (`groupSkus` memo is the single filtered source for list/search/tabs/totals); pack-size badges; qty steppers (44×44); EC = any qty > 0.
- **VisitCheckout** — Total SKU / Total Qty / **Total Rupiah**; brand-grouped "Ringkasan Order" with pack sizes; submit → SPV or offline-save.
- **Profil** — user info, unread notifications badge, Logout. ⚠ version label hardcoded (known issue R7) — verify installed version via Android Settings.

## Offline architecture

SQLite (expo-sqlite, WAL): `local_visits` (+`sync_status`: `local|syncing|synced|failed`), `sync_queue`, `cached_schedule`, `cached_sku`. JWT in expo-secure-store (`sfa_jwt`).

**Sync engine (`src/sync/engine.ts`)** — hardened 2026-07-15:
1. Single-flight mutex — concurrent triggers share one in-flight flush promise.
2. Network-restore trigger debounced 2 s (App.tsx NetInfo listener) — rapid offline↔online flapping causes exactly one flush.
3. Connectivity re-checked before each visit — mid-flush drops stop cleanly, remainder stays queued.
4. Crash recovery — `resetStuckSyncing()` on app boot returns `syncing` rows to `local`.
5. Replay per visit: (checkin unless `server_visit_id` exists) → checkout → submit, all with `offline_mode: true` + original `captured_at`. Server side is idempotent, so retries never duplicate.
6. After a successful flush: pending count updates and **all React-Query caches invalidate** (Home KPI, lists refresh without user action). Home KPI additionally refetches on every screen focus.

## Build & release

```powershell
# Dev
npm install        # postinstall runs patch-package + scripts/patch-cmake.js
npx expo start     # Metro; 'a' for Android

# Quality gates (run before any release)
npx tsc --noEmit
npx jest           # 12 unit tests: sync engine, offline store, GPS checkin, visit flow

# Release APK
# 1) bump versionCode + versionName in android/app/build.gradle AND "version" in app.json
cd android; .\gradlew.bat assembleRelease
# → android/app/build/outputs/apk/release/app-release.apk  (~116 MB)
```

Install over previous version (`adb install -r …`) — SQLite data survives. Users must **re-login** after role/BU changes (JWT carries them).

⚠ **Signing:** release currently signs with the **debug keystore** (see `android/app/build.gradle`) — acceptable for internal sideloading only. Generate a real keystore before any Play Store distribution, and note the `android/` folder is gitignored (version bumps in `build.gradle` must be redone after a fresh `expo prebuild`).

## Conventions
- Design tokens only (`src/theme.ts` — Colors/Spacing/Radius/Shadow/Typography); no hardcoded styles.
- Business Unit brand lists are UPPERCASE and compared case-insensitively (`VisitSurveyScreen.tsx BRAND_GROUPS`) — mirror of backend; keep in sync.
- Every interactive element: `accessibilityLabel` + `accessibilityRole`; decorative icons `accessible={false}`.
- API calls via `getApiClient()` only; 401 triggers global logout; checkout/submit use 45 s timeouts.
- Server data via TanStack Query with explicit `queryKey`s; local visit state via Zustand `offlineStore`.
