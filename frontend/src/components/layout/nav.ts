import type { IconName } from "@/components/ui";
import type { Role } from "@/types";

// ── Types ──────────────────────────────────────────────────────────────────────
export interface NavLeaf {
  to: string;
  label: string;
  roles: Role[];
}

export interface NavGroup {
  kind: "group";
  id: string;
  label: string;
  icon: IconName;
  children: NavLeaf[];
}

export interface NavSingle {
  kind: "single";
  to: string;
  label: string;
  icon: IconName;
  roles: Role[];
}

export type NavItem = NavGroup | NavSingle;

// ── Navigation tree ───────────────────────────────────────────────────────────
// The single source of truth for web menu authorization. Roles not listed here
// (e.g. "salesman", "demo") are mobile-app users and see no web navigation.
export const NAV_TREE: NavItem[] = [
  {
    kind: "single",
    to: "/dashboard",
    label: "Dashboard",
    icon: "chart-bar",
    roles: ["spv", "asm", "ho_admin"],
  },
  {
    kind: "group",
    id: "master-data",
    label: "Master Data",
    icon: "rectangle-stack",
    children: [
      { to: "/route-planner",        label: "Route Planner",     roles: ["spv", "asm", "ho_admin"] },
      { to: "/master-data-pjp",      label: "Master Data PJP",   roles: ["asm", "ho_admin"] },
      { to: "/master-data-salesman", label: "Master Salesman",   roles: ["asm", "ho_admin"] },
      { to: "/target-management",    label: "Target Management", roles: ["spv", "asm", "ho_admin"] },
      { to: "/outlet-salesman",      label: "Outlet & Salesman", roles: ["spv", "asm", "ho_admin"] },
    ],
  },
  {
    kind: "group",
    id: "reports",
    label: "Reports",
    icon: "chart-pie",
    children: [
      { to: "/route-evaluate",    label: "Route Evaluate",    roles: ["spv", "asm", "ho_admin"] },
      { to: "/visits",            label: "Visit & Order",     roles: ["spv", "asm", "dm", "ho_admin"] },
      { to: "/store-opportunity", label: "Store Opportunity", roles: ["asm", "ho_admin"] },
      { to: "/store360",          label: "Store 360°",        roles: ["spv", "asm", "ho_admin"] },
      { to: "/salesman360",       label: "Salesman 360°",     roles: ["spv", "asm", "ho_admin"] },
    ],
  },
  {
    kind: "single",
    to: "/approvals",
    label: "Approvals",
    icon: "check-circle",
    roles: ["spv", "asm", "dm", "ho_admin"],
  },
  {
    kind: "single",
    to: "/import-export",
    label: "Import & Export",
    icon: "arrow-up-down",
    roles: ["dm", "ho_admin"],
  },
  {
    kind: "single",
    to: "/announcements",
    label: "Announcements",
    icon: "megaphone",
    roles: ["spv", "asm", "dm", "ho_admin"],
  },
  {
    kind: "single",
    to: "/administration",
    label: "Administration",
    icon: "cog",
    roles: ["ho_admin"],
  },
  {
    kind: "single",
    to: "/notifications",
    label: "Notifikasi",
    icon: "bell",
    roles: ["spv", "asm", "dm", "ho_admin"],
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────
export function isGroup(item: NavItem): item is NavGroup {
  return item.kind === "group";
}

export function canSee(item: NavItem, role: Role): boolean {
  if (isGroup(item)) return item.children.some((c) => c.roles.includes(role));
  return item.roles.includes(role);
}

export function groupIsActive(group: NavGroup, pathname: string): boolean {
  return group.children.some(
    (c) => pathname === c.to || pathname.startsWith(c.to + "/"),
  );
}

// ── Access control ────────────────────────────────────────────────────────────
// NAV_TREE is the single source of truth for BOTH menu visibility and route
// access, so the two can never drift apart. Previously only the menu consulted
// it, which meant any authenticated user could open a page they had no entry
// for simply by typing the URL — the backend refused the data, but the shell
// still rendered.

/** Every path this role may open, flattened across groups. */
export function allowedPathsFor(role: Role): string[] {
  const out: string[] = [];
  for (const item of NAV_TREE) {
    if (isGroup(item)) {
      for (const c of item.children) if (c.roles.includes(role)) out.push(c.to);
    } else if (item.roles.includes(role)) {
      out.push(item.to);
    }
  }
  return out;
}

/**
 * May this role open this pathname? Matches the exact path or a nested child
 * route (`/visits/abc` is covered by `/visits`), while refusing a mere string
 * prefix (`/visitsX` is NOT covered by `/visits`).
 */
export function canAccessPath(role: Role, pathname: string): boolean {
  return allowedPathsFor(role).some(
    (p) => pathname === p || pathname.startsWith(p + "/"),
  );
}

/**
 * Landing route for a role. `/dashboard` is not universal — a Distributor
 * cannot see it — so anything that used to hard-code it (index redirect,
 * post-login redirect, unknown-path fallback) must ask for this instead.
 * Returns null for roles with no web navigation at all (mobile-only).
 */
export function defaultPathFor(role: Role): string | null {
  return allowedPathsFor(role)[0] ?? null;
}

/**
 * Nav items to render for a role. A group whose visible children collapse to a
 * single entry is promoted to a top-level link: a Distributor sees only
 * "Visit & Order", not a "Reports" group wrapping one item. Roles with two or
 * more visible children in a group are unaffected.
 */
export function visibleNavFor(role: Role): NavItem[] {
  const out: NavItem[] = [];
  for (const item of NAV_TREE) {
    if (!isGroup(item)) {
      if (item.roles.includes(role)) out.push(item);
      continue;
    }
    const visible = item.children.filter((c) => c.roles.includes(role));
    if (visible.length === 0) continue;
    if (visible.length === 1) {
      out.push({
        kind: "single",
        to: visible[0].to,
        label: visible[0].label,
        icon: item.icon,
        roles: visible[0].roles,
      });
    } else {
      out.push({ ...item, children: visible });
    }
  }
  return out;
}
