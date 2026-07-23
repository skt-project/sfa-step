# 12 — STEP Design System

**Date:** 2026-07-22 · **Applies to:** STEP Web (`sfa-step/frontend`) · **Status:** established (tokens + logo + login/sidebar shipped on `feature/step-rebrand`); page-by-page rollout in progress.

The single source of truth for STEP's product identity. **Every new screen must be built from the tokens and component classes below — never hardcode hex colors, ad-hoc radii, or one-off shadows.** The primitives live in:

- **Tokens** → [`tailwind.config.js`](../../frontend/tailwind.config.js) (colors, radius, shadow, animation)
- **Component classes** → [`src/index.css`](../../frontend/src/index.css) (`.btn-*`, `.card`, `.input`, `.badge-*`, `.kpi-tile`, …)
- **Logo** → [`src/components/brand/StepLogo.tsx`](../../frontend/src/components/brand/StepLogo.tsx)

---

## 1. Brand hierarchy

STEP is the **product**; Skintific is the **company**. Never make Skintific more dominant than STEP.

```
[STEP logo]
STEP                              ← strongest element
Sales Team Execution Platform     ← tagline (medium)
by Skintific                      ← subtle, small
```

- **STEP** also stands for *Step of the Call* — the atomic unit of field sales execution.
- Full lockup (logo + all three lines): login/landing, splash, about.
- Compact lockup (mark + "STEP" + tagline): sidebar, headers.
- Mark only: favicon, launcher, avatars, tight spaces.

## 2. Logo

Use the [`StepLogo`](../../frontend/src/components/brand/StepLogo.tsx) component — never paste raw SVG or screenshot it.

| Prop | Default | Use |
|---|---|---|
| `size` | `40` | pixel size of the square mark |
| `container` | `true` | `true` = white glyph on gradient tile (dark/photo backgrounds, launcher); `false` = gradient glyph on transparent (light surfaces) |
| `title` | `"STEP"` | accessible label; set `""` when a text "STEP" sits beside it (marks it decorative) |

**Meaning:** three ascending steps rising to a checkpoint = progress · route · outlet visit · achievement.
**Rules:** keep clear space ≥ 25% of the mark on all sides · min size 24px · never recolor, rotate, stretch, or add effects beyond the approved `drop-shadow` · favicon lives at [`frontend/public/favicon.svg`](../../frontend/public/favicon.svg).

## 3. Color

### Brand (Skintific blue) — identity & accents
| Token | Hex | Use |
|---|---|---|
| `brand-50/100/200` | `#f0f8ff` `#e0f1ff` `#c5e6ff` | tints, backgrounds, hover fills |
| `brand-300` | `#9dd6ff` | subtle borders, glows |
| **`brand-400`** | **`#7ccbff`** | **accent** |
| **`brand-500`** | **`#5cb8ff`** | **primary identity** (logo, gradients, focus glow) |
| `brand-600` | `#3aa0f0` | interactive hover |
| `brand-700` | `#2884d1` | **interactive / accessible text on white** (CTA gradient end, links) |
| `brand-800/900` | `#236aa6` `#215a86` | deep text, pressed |

> **Accessibility:** `#5CB8FF` is the *identity* hue but is too light for white text. For interactive fills/text use **`brand-600/700`**; the primary CTA is a `from-brand-500 to-brand-700` gradient so the legible end carries the label. Body text stays on the `slate` ramp.

### Supporting ramps
- **`slate`** — text (`slate-900/800/700`), secondary (`slate-500/400`), borders (`slate-200/100`), surfaces (`slate-50`).
- **`primary`** (legacy blue, `600=#2563eb`) — still powers most existing interactive classes (`.btn-primary`, `.tab-active`, `.chip-active`). Migrating these to `brand` is a tracked rollout item; **do not swap wholesale** (contrast + blast radius). New brand-forward surfaces use `brand-*` directly.

### Status colors
| Meaning | Ramp | Classes |
|---|---|---|
| Success | `emerald` | `.badge-green` `.alert-success` `.dot-green` `.progress-fill-green` |
| Warning | `amber` | `.badge-yellow` `.alert-warning` `.dot-yellow` `.progress-fill-amber` |
| Error | `red` | `.badge-red` `.alert-danger` `.btn-danger` `.dot-red` |
| Info | `blue` / `brand` | `.badge-blue` `.alert-info` `.dot-blue` |

## 4. Typography

**Font:** Inter (loaded in `index.html`), fallbacks in `fontFamily.sans`.

| Role | Style | Reference |
|---|---|---|
| STEP wordmark | `text-6xl/7xl font-extrabold tracking-tight`, brand gradient text | login hero |
| Page title | `text-xl font-bold text-slate-900` | `.page-hero-title` / `.detail-hero-title` |
| Section title | `text-base font-semibold text-slate-800` | `.section-heading-title` |
| Card title | `text-sm font-semibold text-slate-900` | `.card-title` |
| KPI value | `text-2xl font-bold tabular-nums` | `.stat-value` / `.kpi-tile-value` |
| Body | `text-sm text-slate-700` | default |
| Caption / hint | `text-xs text-slate-500` | `.form-hint` |
| Caps label | `text-2xs (11px) font-semibold uppercase tracking-wide` | `.form-label` / `.stat-label` |

Weights: 400 body · 500 medium · 600 semibold (labels/titles) · 700 bold (values) · 800 wordmark. Numbers in metrics use `tabular-nums`.

## 5. Spacing — 8px grid

Rhythm is **8px**. Prefer Tailwind steps that land on the grid: `2`=8 · `3`=12 · `4`=16 · `5`=20 · `6`=24 · `8`=32 · `10`=40 · `12`=48px. Card padding `p-5`(20)/`p-6`(24); section gaps `space-y-6`(24); page padding `p-6 lg:p-8` (`.page-content`). Avoid arbitrary values off the grid.

## 6. Radius

| Token | px | Use |
|---|---|---|
| `sm` | 6 | chips, small controls |
| `md`/`DEFAULT` | 8 | inputs, buttons |
| `lg` | 12 | buttons/inputs (brand-forward), badges area |
| `xl` | 14 | **cards (default)** |
| `2xl` | 16 | modals, prominent cards |
| `3xl` | 20 | login/glass card, hero surfaces |
| `full` | — | pills, badges, avatars, progress tracks |

## 7. Elevation (shadow)

| Level | Token | Use |
|---|---|---|
| 1 — resting | `shadow-card` | cards, tiles |
| 2 — hover | `shadow-card-md` | `.card-hover`, `.hover-lift` |
| 3 — overlay | `shadow-card-lg` | modals, toasts, popovers |
| CTA | `shadow-primary` / `shadow-brand` | primary buttons, brand CTAs |
| Brand hero | `shadow-brand-lg` | landing CTA hover |
| Glass | `shadow-glass` | login/glassmorphic card |

Keep it flat: most surfaces are level 1; reserve level 3 for true overlays.

## 8. Components (reuse these classes)

**Buttons** — `.btn-primary` · `.btn-secondary` · `.btn-danger` · `.btn-ghost` · `.btn-icon`; sizes `.btn-xs/-sm/-lg`. Brand CTA (login) pattern: `rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-brand hover:-translate-y-0.5`.

**Cards** — `.card` (base), `.card-hover`, `.card-title`/`.card-subtitle`/`.card-section`. **Dashboard KPI card:** `.kpi-tile` (icon + value + label) or `.stat-card`; delta `.kpi-tile-delta-up/-down`. **Status rail:** `.rail-blue/-green/-amber/-red`.

**Inputs** — `.input` (+ `.input-sm`, `.input-error`), `.form-label`, `.form-hint`, `.form-error`; brand focus add `focus:ring-brand-500/30 focus:border-brand-400`. Search: `.search-bar`.

**Badges & dots** — `.badge-{blue,green,yellow,red,gray,purple}`, `.dot-{…}`. **Chips** — `.chip` / `.chip-active`.

**Feedback** — `.alert-{info,success,warning,danger}`, `.toast-{success,error,warning,info}`, `.skeleton` (shimmer loaders), `.empty-state` (`-icon/-title/-text`).

**Layout** — `.page-content`, `.page-inner`, `.page-hero`, `.section-heading`, `.table` + `.table-container`, `.modal-backdrop`/`.modal-panel`, `.pagination`, `.fab`.

## 9. Sidebar

Dark rail (`bg-slate-900`, `w-60`). Top: `StepLogo` mark + hierarchy (STEP / Sales Team Execution Platform / by Skintific). Nav from [`nav.ts`](../../frontend/src/components/layout/nav.ts) (RBAC-filtered). Active leaf = `bg-primary-600 text-white`; hover = `bg-white/[0.07]`; grouped items collapse/expand. Footer: user initials + role + logout. *(Rollout: active/hover state migrating to `brand`.)*

## 10. Header / TopNav

Page headers use `.page-hero` (title + subtitle) or `.detail-hero`. Keep a consistent height, left-aligned title, right-aligned actions (search, notifications bell with unread badge, user). *(Rollout item: unify `TopNav` styling with these tokens across all pages.)*

## 11. Animation

Tokens (in `tailwind.config.js`): `animate-fade-in` · `slide-up`/`slide-down` · `scale-in` (micro, 150–200ms) · `fade-up` (entrance, 600ms) · `blob`/`blob-slow` + `float` + `glow` (ambient landing motion, 8–32s). Easing `cubic-bezier(0.22,1,0.36,1)` for entrances. Stagger hero elements with `animationDelay` (80/150/220/300ms).

**Rules:** tasteful and purposeful — entrance + hover feedback, not decoration. Everything degrades via the global `prefers-reduced-motion` block in `index.css` (do not add motion that ignores it).

## 12. Accessibility (non-negotiable)

Keyboard focus visible everywhere (global `:focus-visible` ring) · ARIA labels on icon-only controls · status never by color alone (pair with icon/text) · body/interactive text meets WCAG AA (use `brand-600/700`, `slate-700+`) · respect reduced motion · responsive font/layout, no horizontal overflow.

---

### Rollout checklist (applying this system app-wide)
- [x] Tokens (`brand` scale, animations, shadows) · `StepLogo` · favicon
- [x] Login / landing · Sidebar brand block
- [ ] TopNav / page headers unified
- [ ] Dashboard KPI cards → `.kpi-tile` + brand
- [ ] Empty states, skeleton loaders, error pages
- [ ] Modals/dialogs, toasts consistency pass
- [ ] Migrate app-wide `primary` → `brand` on interactive states (contrast-checked)
- [ ] Written design-system parity check against every page
