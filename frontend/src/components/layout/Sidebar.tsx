import { useState, useEffect } from "react";
import { NavLink, Link, useNavigate, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/store/authStore";
import { Icon } from "@/components/ui";
import { StepLogo } from "@/components/brand/StepLogo";
import type { Notification, Role } from "@/types";
import { fetchNotifications } from "@/api/notifications";
import { NAV_TREE, isGroup, canSee, groupIsActive } from "./nav";

// ── Sidebar ───────────────────────────────────────────────────────────────────
export default function Sidebar() {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const role = user?.role as Role;

  const { data: notifications } = useQuery<Notification[]>({
    queryKey: ["notifications"],
    queryFn:  fetchNotifications,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
  const unreadCount = (notifications ?? []).filter((n) => !n.is_read).length;

  const [openGroups, setOpenGroups] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    for (const item of NAV_TREE) {
      if (isGroup(item) && groupIsActive(item, location.pathname)) {
        initial.add(item.id);
      }
    }
    return initial;
  });

  useEffect(() => {
    for (const item of NAV_TREE) {
      if (isGroup(item) && groupIsActive(item, location.pathname)) {
        setOpenGroups((prev) => {
          if (prev.has(item.id)) return prev;
          return new Set([...prev, item.id]);
        });
        break;
      }
    }
  }, [location.pathname]);

  const toggleGroup = (id: string) =>
    setOpenGroups((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const initials = user?.username?.[0]?.toUpperCase() ?? "?";

  return (
    <aside className="w-60 min-h-screen bg-slate-900 flex flex-col shrink-0">
      {/* ── Brand ── */}
      <div className="px-5 py-5 border-b border-white/10 shrink-0">
        <Link
          to="/dashboard"
          aria-label="STEP — Beranda"
          className="flex items-center gap-3 rounded-xl hover:opacity-90 transition-opacity -m-1 p-1"
        >
          <StepLogo size={38} title="" className="shrink-0 drop-shadow-[0_4px_10px_rgba(92,184,255,0.35)]" />
          <div className="min-w-0 leading-none">
            <p className="text-white font-extrabold text-base tracking-tight">STEP</p>
            <p className="text-slate-400 text-[0.65rem] mt-1 truncate">Sales Team Execution Platform</p>
            <p className="text-slate-500 text-[0.6rem] mt-0.5">by Skintific</p>
          </div>
        </Link>
      </div>

      {/* ── Navigation ── */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-0.5" aria-label="Main navigation">
        {NAV_TREE.filter((item) => canSee(item, role)).map((item) => {
          if (isGroup(item)) {
            const open    = openGroups.has(item.id);
            const active  = groupIsActive(item, location.pathname);
            const visible = item.children.filter((c) => c.roles.includes(role));

            return (
              <div key={item.id}>
                <button
                  onClick={() => toggleGroup(item.id)}
                  aria-expanded={open}
                  aria-controls={`nav-group-${item.id}`}
                  className={`
                    w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm
                    font-medium transition-all duration-150 select-none
                    ${active
                      ? "bg-white/10 text-white"
                      : "text-slate-400 hover:bg-white/[0.07] hover:text-slate-100"}
                  `}
                >
                  <Icon name={item.icon} className="w-4 h-4 shrink-0" />
                  <span className="flex-1 text-left truncate">{item.label}</span>
                  <Icon
                    name="chevron-right"
                    className={`w-3.5 h-3.5 shrink-0 transition-transform duration-200 ${open ? "rotate-90" : ""}`}
                  />
                </button>

                <div
                  id={`nav-group-${item.id}`}
                  style={{ maxHeight: open ? "24rem" : "0px" }}
                  className="overflow-hidden transition-[max-height] duration-200 ease-in-out"
                >
                  <div className="mt-0.5 ml-3 pl-3 border-l border-white/10 space-y-0.5 pb-1">
                    {visible.map((child) => (
                      <NavLink
                        key={child.to}
                        to={child.to}
                        className={({ isActive }) =>
                          `flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm
                           transition-all duration-150
                           ${isActive
                             ? "bg-primary-600 text-white font-semibold"
                             : "text-slate-400 hover:bg-white/[0.07] hover:text-slate-100 font-normal"
                           }`
                        }
                      >
                        <span aria-hidden="true" className="w-1 h-1 rounded-full bg-current opacity-60 shrink-0" />
                        <span className="truncate">{child.label}</span>
                      </NavLink>
                    ))}
                  </div>
                </div>
              </div>
            );
          }

          const badge = item.to === "/notifications" && unreadCount > 0
            ? unreadCount
            : null;

          return (
            <NavLink
              key={item.to}
              to={item.to}
              aria-label={badge !== null ? `${item.label}, ${badge} belum dibaca` : undefined}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium
                 transition-all duration-150
                 ${isActive
                   ? "bg-primary-600 text-white shadow-sm"
                   : "text-slate-400 hover:bg-white/[0.07] hover:text-slate-100"
                 }`
              }
            >
              <Icon name={item.icon} className="w-4 h-4 shrink-0" />
              <span className="flex-1 truncate">{item.label}</span>
              {badge !== null && (
                <span aria-hidden="true" className="ml-auto text-xs bg-red-500 text-white rounded-full px-1.5 min-w-[18px] text-center font-bold leading-5">
                  {badge > 99 ? "99+" : badge}
                </span>
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* ── User footer ── */}
      <div className="px-4 py-4 border-t border-white/10 shrink-0">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-white text-sm font-bold shrink-0">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-white text-sm font-medium truncate">{user?.username}</p>
            <p className="text-slate-500 text-2xs uppercase tracking-wide mt-0.5">
              {user?.role?.replace(/_/g, " ")}
            </p>
          </div>
        </div>
        <button
          onClick={() => {
            qc.clear();
            logout();
            navigate("/login", { replace: true });
          }}
          className="w-full text-slate-500 hover:text-slate-200 text-xs py-1.5
                     transition-colors duration-150 flex items-center gap-2 group"
        >
          <Icon name="arrow-right-on-rectangle" className="w-4 h-4 shrink-0" />
          <span>Keluar</span>
        </button>
      </div>
    </aside>
  );
}
