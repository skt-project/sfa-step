import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { canAccessPath, defaultPathFor } from "@/components/layout/nav";
import type { Role } from "@/types";
import { Toaster } from "@/components/ui";
import Layout from "@/components/layout/Layout";
import Login from "@/pages/Login";
import ErrorBoundary from "@/components/ErrorBoundary";

// ── Lazy-loaded pages (code-split per route) ───────────────────────────────
const Dashboard         = lazy(() => import("@/pages/Dashboard"));
const RoutePlanner      = lazy(() => import("@/pages/RoutePlanner"));
const RouteEvaluate     = lazy(() => import("@/pages/RouteEvaluate"));
const TargetManagement  = lazy(() => import("@/pages/TargetManagement"));
const Approvals         = lazy(() => import("@/pages/Approvals"));
const Announcements     = lazy(() => import("@/pages/Announcements"));
const Reports           = lazy(() => import("@/pages/Reports"));
const MasterDataPjp     = lazy(() => import("@/pages/MasterDataPjp"));
const MasterDataSalesman = lazy(() => import("@/pages/MasterDataSalesman"));
const OutletSalesman    = lazy(() => import("@/pages/OutletSalesman"));
const Store360          = lazy(() => import("@/pages/Store360"));
const Salesman360       = lazy(() => import("@/pages/Salesman360"));
const StoreOpportunity  = lazy(() => import("@/pages/StoreOpportunity"));
const Visits            = lazy(() => import("@/pages/Visits"));
const VisitDetail       = lazy(() => import("@/pages/VisitDetail"));
const Administration    = lazy(() => import("@/pages/Administration"));
const ImportExport      = lazy(() => import("@/pages/ImportExport"));
const Notifications     = lazy(() => import("@/pages/Notifications"));

// ── Per-page loading skeleton ──────────────────────────────────────────────
function PageFallback() {
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-5 animate-pulse" aria-hidden="true">
      <div className="flex items-center justify-between">
        <div className="h-6 w-44 bg-slate-200 rounded" />
        <div className="h-9 w-28 bg-slate-200 rounded-lg" />
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card h-24 bg-slate-50" />
        ))}
      </div>
      <div className="card h-72 bg-slate-50" />
    </div>
  );
}

// ── Route wrapper: error isolation + lazy-load skeleton ───────────────────
function RoutedPage({ children }: { children: ReactNode }) {
  return (
    <RoleGuard>
      <ErrorBoundary>
        <Suspense fallback={<PageFallback />}>{children}</Suspense>
      </ErrorBoundary>
    </RoleGuard>
  );
}

// ── Role-aware landing target ──────────────────────────────────────────────
// "/dashboard" is NOT a universal home: a Distributor has no Dashboard entry.
// Anything that used to hard-code it must resolve the role's first allowed
// route instead, or a Distributor lands on a page it is then bounced off.
function HomeRedirect() {
  const role = useAuthStore((s) => s.user?.role) as Role | undefined;
  const home = role ? defaultPathFor(role) : null;
  return <Navigate to={home ?? "/login"} replace />;
}

// ── Route-level RBAC ───────────────────────────────────────────────────────
// Menu visibility alone is not access control: without this, any authenticated
// user could open /administration by typing the URL. The backend still refused
// the data, but the page shell rendered. Authorization is derived from NAV_TREE
// so the menu and the router can never disagree.
function RoleGuard({ children }: { children: ReactNode }) {
  const role = useAuthStore((s) => s.user?.role) as Role | undefined;
  const location = useLocation();
  if (!role) return <Navigate to="/login" replace />;
  if (!canAccessPath(role, location.pathname)) return <HomeRedirect />;
  return <>{children}</>;
}

// ── Auth guard ─────────────────────────────────────────────────────────────
function AuthGuard({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const location = useLocation();

  // No useEffect rehydrate — the store initializes synchronously from
  // localStorage (see authStore.ts loadInitialState), so isAuthenticated is
  // already correct on the first render.  The old async rehydrate caused a
  // race where the login page flashed and then redirected back to dashboard.
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}

// ── Routes ─────────────────────────────────────────────────────────────────
function AppRoutes() {
  const { isAuthenticated } = useAuthStore();

  return (
    <Routes>
      <Route
        path="/login"
        element={isAuthenticated ? <HomeRedirect /> : <Login />}
      />

      <Route
        element={
          <AuthGuard>
            <Layout />
          </AuthGuard>
        }
      >
        <Route index element={<HomeRedirect />} />

        <Route path="dashboard"          element={<RoutedPage><Dashboard /></RoutedPage>} />
        <Route path="route-planner"      element={<RoutedPage><RoutePlanner /></RoutedPage>} />
        <Route path="route-evaluate"     element={<RoutedPage><RouteEvaluate /></RoutedPage>} />
        <Route path="target-management"  element={<RoutedPage><TargetManagement /></RoutedPage>} />
        <Route path="approvals"          element={<RoutedPage><Approvals /></RoutedPage>} />
        <Route path="announcements"      element={<RoutedPage><Announcements /></RoutedPage>} />
        <Route path="reports"            element={<RoutedPage><Reports /></RoutedPage>} />

        {/* Master Data */}
        <Route path="master-data-pjp"     element={<RoutedPage><MasterDataPjp /></RoutedPage>} />
        <Route path="master-data-salesman" element={<RoutedPage><MasterDataSalesman /></RoutedPage>} />
        <Route path="outlet-salesman"     element={<RoutedPage><OutletSalesman /></RoutedPage>} />

        {/* 360° Views */}
        <Route path="store360"          element={<RoutedPage><Store360 /></RoutedPage>} />
        <Route path="salesman360"       element={<RoutedPage><Salesman360 /></RoutedPage>} />
        <Route path="store-opportunity" element={<RoutedPage><StoreOpportunity /></RoutedPage>} />

        {/* Visits & Demand */}
        <Route path="visits"            element={<RoutedPage><Visits /></RoutedPage>} />
        <Route path="visits/:visitId"   element={<RoutedPage><VisitDetail /></RoutedPage>} />


        {/* Admin */}
        <Route path="administration"    element={<RoutedPage><Administration /></RoutedPage>} />
        <Route path="import-export"     element={<RoutedPage><ImportExport /></RoutedPage>} />
        <Route path="notifications"     element={<RoutedPage><Notifications /></RoutedPage>} />
      </Route>

      {/* Fallback */}
      <Route
        path="*"
        element={
          isAuthenticated
            ? <HomeRedirect />
            : <Navigate to="/login" replace />
        }
      />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
      <Toaster />
    </BrowserRouter>
  );
}
