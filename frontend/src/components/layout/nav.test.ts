import { describe, it, expect } from "vitest";
import { NAV_TREE, canSee, isGroup, groupIsActive, type NavGroup } from "./nav";
import type { Role } from "@/types";

const ALL_ROLES: Role[] = ["salesman", "spv", "asm", "dm", "ho_admin", "demo"];
const WEB_ROLES: Role[] = ["spv", "asm", "dm", "ho_admin"];
const MOBILE_ONLY: Role[] = ["salesman", "demo"];

function topLevelLabelsFor(role: Role): string[] {
  return NAV_TREE.filter((i) => canSee(i, role)).map((i) => i.label);
}

describe("navigation RBAC matrix", () => {
  it("hides every menu item from mobile-only roles (salesman, demo)", () => {
    for (const role of MOBILE_ONLY) {
      expect(NAV_TREE.filter((i) => canSee(i, role))).toEqual([]);
    }
  });

  it("shows Administration only to ho_admin", () => {
    for (const role of WEB_ROLES) {
      expect(topLevelLabelsFor(role).includes("Administration")).toBe(role === "ho_admin");
    }
  });

  it("shows Import & Export only to dm and ho_admin", () => {
    expect(topLevelLabelsFor("spv")).not.toContain("Import & Export");
    expect(topLevelLabelsFor("asm")).not.toContain("Import & Export");
    expect(topLevelLabelsFor("dm")).toContain("Import & Export");
    expect(topLevelLabelsFor("ho_admin")).toContain("Import & Export");
  });

  it("keeps Master Data PJP/Salesman out of the SPV's reach", () => {
    const md = NAV_TREE.find((i) => isGroup(i) && i.id === "master-data") as NavGroup;
    for (const to of ["/master-data-pjp", "/master-data-salesman"]) {
      const leaf = md.children.find((c) => c.to === to)!;
      expect(leaf.roles).not.toContain("spv");
      expect(leaf.roles).toEqual(expect.arrayContaining(["asm", "dm", "ho_admin"]));
    }
  });

  it("every leaf grants at least one role and only known roles", () => {
    const known = new Set<Role>(ALL_ROLES);
    for (const item of NAV_TREE) {
      const roleLists = isGroup(item) ? item.children.map((c) => c.roles) : [item.roles];
      for (const roles of roleLists) {
        expect(roles.length).toBeGreaterThan(0);
        for (const r of roles) expect(known.has(r)).toBe(true);
      }
    }
  });

  it("a group is visible iff at least one of its children is visible to the role", () => {
    for (const item of NAV_TREE) {
      if (!isGroup(item)) continue;
      for (const role of ALL_ROLES) {
        const anyChildVisible = item.children.some((c) => c.roles.includes(role));
        expect(canSee(item, role)).toBe(anyChildVisible);
      }
    }
  });

  it("ho_admin can see every top-level entry", () => {
    for (const item of NAV_TREE) {
      expect(canSee(item, "ho_admin")).toBe(true);
    }
  });
});

describe("groupIsActive", () => {
  const md = NAV_TREE.find((i) => isGroup(i) && i.id === "master-data") as NavGroup;

  it("matches an exact child path", () => {
    expect(groupIsActive(md, "/route-planner")).toBe(true);
  });

  it("matches a nested child path", () => {
    expect(groupIsActive(md, "/route-planner/123")).toBe(true);
  });

  it("does not match an unrelated path", () => {
    expect(groupIsActive(md, "/dashboard")).toBe(false);
  });

  it("does not match a path that only shares a string prefix (guards against startsWith bug)", () => {
    expect(groupIsActive(md, "/route-plannerX")).toBe(false);
  });
});
