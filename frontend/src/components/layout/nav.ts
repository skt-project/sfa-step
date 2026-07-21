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
    roles: ["spv", "asm", "dm", "ho_admin"],
  },
  {
    kind: "group",
    id: "master-data",
    label: "Master Data",
    icon: "rectangle-stack",
    children: [
      { to: "/route-planner",        label: "Route Planner",     roles: ["spv", "asm", "dm", "ho_admin"] },
      { to: "/master-data-pjp",      label: "Master Data PJP",   roles: ["asm", "dm", "ho_admin"] },
      { to: "/master-data-salesman", label: "Master Salesman",   roles: ["asm", "dm", "ho_admin"] },
      { to: "/target-management",    label: "Target Management", roles: ["spv", "asm", "dm", "ho_admin"] },
      { to: "/outlet-salesman",      label: "Outlet & Salesman", roles: ["spv", "asm", "dm", "ho_admin"] },
    ],
  },
  {
    kind: "group",
    id: "reports",
    label: "Reports",
    icon: "chart-pie",
    children: [
      { to: "/route-evaluate",    label: "Route Evaluate",    roles: ["spv", "asm", "dm", "ho_admin"] },
      { to: "/visits",            label: "Visit & Order",     roles: ["spv", "asm", "dm", "ho_admin"] },
      { to: "/store-opportunity", label: "Store Opportunity", roles: ["asm", "dm", "ho_admin"] },
      { to: "/store360",          label: "Store 360°",        roles: ["spv", "asm", "dm", "ho_admin"] },
      { to: "/salesman360",       label: "Salesman 360°",     roles: ["spv", "asm", "dm", "ho_admin"] },
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
