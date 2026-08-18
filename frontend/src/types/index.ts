// ── Auth ──────────────────────────────────────────────────────────────────────
export interface User {
  user_id: string;
  username: string;
  full_name: string;
  role: Role;
  email: string | null;
  territory: string | null;
  distributor_code: string | null;
  brand_group: string | null;
  salesman_sk: string | null;
  is_active: boolean;
}

export type Role = "salesman" | "spv" | "asm" | "dm" | "ho_admin" | "demo";

// ── Dashboard ─────────────────────────────────────────────────────────────────
export interface DashboardKpi {
  label: string;
  value: string | number;
  sub?: string;
  trend?: "up" | "down" | "neutral";
  color?: "blue" | "green" | "yellow" | "red";
}

export interface ComplyBrand {
  brand: string;
  management_target: number;
  spv_target: number;
  comply_pct: number;
  comply_status: "Comply" | "Under Comply" | "Over Target" | "No Data";
}

export interface LeaderboardRow {
  rank: number;
  salesman_name: string;
  salesman_sk: string;
  achievement_pct: number;
  route_compliance_pct: number;
  coverage_pct: number;
}

// ── Route ─────────────────────────────────────────────────────────────────────
export type DayId = "Senin" | "Selasa" | "Rabu" | "Kamis" | "Jumat" | "Sabtu";

export interface RouteStore {
  route_plan_sk: string;
  outlet_sk: string;
  store_name: string;
  source_outlet_code: string;
  store_grade: string | null;
  address: string | null;
  last_visit_date: string | null;
  visit_day_of_week: DayId;
  visit_week_pattern: string;
  sequence_no: number;
}

export interface SalesmanRoute {
  salesman_sk: string;
  salesman_name: string;
  source_salesman_code: string;
  region: string | null;
  distributor_code: string | null;
  stores_per_day: Record<DayId, RouteStore[]>;
  total_stores: number;
  achievement_pct: number | null;
  compliance_pct: number | null;
}

// ── Target ────────────────────────────────────────────────────────────────────
export interface SpvTargetRow {
  spv_target_id: string;
  salesman_sk: string;
  salesman_name: string;
  brand: string;
  period_month: string;
  spv_target_amount: number;
  approval_status: "draft" | "submitted" | "approved" | "rejected";
}

export interface TargetComply {
  brand: string;
  period_month: string;
  management_target_total: number;
  spv_target_total: number;
  comply_pct: number;
  comply_status: string;
}

// ── Route Evaluate ────────────────────────────────────────────────────────────
export interface EvaluateTeamRow {
  salesman_sk: string;
  salesman_name: string;
  planned: number;
  call_count: number;
  effective_call_count: number;
  ec_rate_pct: number;
}

export interface EvaluateStoreRow {
  outlet_sk: string;
  store_name: string;
  store_grade: string | null;
  planned: boolean;
  is_call: boolean;
  is_effective: boolean | null;
  status: "OK" | "Low Conversion" | "Belum Terlaksana";
}

// ── Approval ──────────────────────────────────────────────────────────────────
export type ApprovalType = "target_adjust" | "tier_override" | "reopen";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "revision";

export interface ApprovalRequest {
  approval_id: string;
  type: ApprovalType;
  title: string;
  submitted_by: string;
  submitted_at: string;
  current_value: number | string | null;
  proposed_value: number | string;
  reason: string;
  status: ApprovalStatus;
  sla_hours: number;
  comments: ApprovalComment[];
}

export interface ApprovalComment {
  author: string;
  role: string;
  body: string;
  created_at: string;
}

// ── Announcement ──────────────────────────────────────────────────────────────
export type AnnouncementType = "Campaign" | "Policy" | "Meeting" | "Distributor" | "Training";

export interface Announcement {
  announcement_id: string;
  type: AnnouncementType;
  title: string;
  body: string;
  audience: string;
  created_by: string;
  created_at: string;
}

// ── Salesman / Outlet ─────────────────────────────────────────────────────────
export interface Salesman {
  salesman_sk: string;
  source_salesman_code: string;
  salesman_name: string;
  salesman_type: string;
  brand_group: string | null;
  distributor_code: string | null;
  region: string | null;
  spv_name: string | null;
  asm_name: string | null;
  is_active: boolean;
}

export interface Outlet {
  outlet_sk: string;
  outlet_id: string;
  source_outlet_code: string;
  store_name: string;
  store_grade: string | null;
  tier: string | null;
  brand: string | null;
  channel: string | null;
  region: string | null;
  kecamatan: string | null;
  city: string | null;
  address: string | null;
  spv_name: string | null;
  salesman_name: string | null;
  salesman_code: string | null;
  salesman_sk: string | null;
  is_active: boolean;
}

// ── Visit & Demand ────────────────────────────────────────────────────────────
export type VisitStatus = "DRAFT" | "CHECKED_IN" | "CHECKED_OUT" | "SUBMITTED";
export type VisitApprovalStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "PENDING_SPV"
  | "SPV_APPROVED"
  | "ASM_APPROVED"
  | "DDM_APPROVED"
  | "REVISION_REQUIRED"
  | "COMPLETED"
  | "REJECTED";

export interface VisitItem {
  visit_item_id: string;
  sku_id: string;
  sku_name: string | null;
  brand: string | null;
  category: string | null;
  sku_size: string | null;       // product size label, e.g. "20ml"
  stp: number | null;
  qty: number | null;            // original quantity from SE
  final_qty: number | null;      // SPV-adjusted quantity (null = use qty)
  demand: number | null;         // reflects final_qty * stp when final_qty is set
  price_for_store: number | null;  // distributor admin sets selling price to store
  warehouse_stock_qty: number | null;  // from dist_stock (may be null)
}

export interface Visit {
  visit_id: string;
  salesman_sk: string;
  salesman_name: string | null;
  outlet_sk: string | null;
  store_name: string | null;
  distributor_code: string | null;
  schedule_id: string | null;
  visit_date: string;
  visit_type: string;
  brand_group: string | null;
  checkin_time: string | null;
  checkin_latitude: number | null;
  checkin_longitude: number | null;
  checkin_photo_url: string | null;
  checkin_distance_m: number | null;
  gps_warning: boolean;
  checkout_time: string | null;
  checkout_latitude: number | null;
  checkout_longitude: number | null;
  checkout_photo_url: string | null;
  total_demand: number | null;
  final_demand: number | null;   // recalculated from final_qty (null until SPV edits)
  effective_call: "YES" | "NO" | null;
  notes: string | null;
  duration_minutes: number | null;
  visit_status: VisitStatus | null;
  approval_status: VisitApprovalStatus | null;
  spv_username: string | null;
  spv_approved_at: string | null;
  asm_username: string | null;
  asm_approved_at: string | null;
  ddm_username: string | null;
  ddm_approved_at: string | null;
  rejection_notes: string | null;
  revision_count: number | null;
  adjustment_amount: number | null;   // distributor invoice adjustment (+/-)
  adjustment_note: string | null;
  download_count: number;
  created_at: string | null;
  updated_at: string | null;
  items: VisitItem[];
}

export interface VisitListResponse {
  items: Visit[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
}

// ── Skipped Store ─────────────────────────────────────────────────────────────
export type SkippedStoreStatus =
  | "PENDING_SPV"
  | "RETURNED_TO_SALESMAN"
  | "EXECUTED_BY_SPV"
  | "EXPIRED";

export interface SkippedStore {
  skipped_store_id: string;
  salesman_sk: string;
  outlet_sk: string;
  outlet_name: string | null;
  distributor_code: string | null;
  brand_group: string | null;
  week_iso: string;
  visit_date: string;
  skipped_at: string;
  status: SkippedStoreStatus;
  spv_action_by: string | null;
  spv_action_at: string | null;
  spv_notes: string | null;
  executed_visit_id: string | null;
}

// ── External distributor transactions ─────────────────────────────────────────
// Sourced from an external spreadsheet, NOT from the SFA visit pipeline. Kept in
// its own types so an SFA schema change cannot silently alter this contract.
export interface ExtTransactionItem {
  ext_visit_item_id: string;
  sku_id: string | null;
  sku_name: string | null;
  brand: string | null;
  category: string | null;
  qty: number | null;
  stp: number | null;
  demand: number | null;
  line_value: number | null;
}

export interface ExtTransaction {
  ext_visit_id: string;
  visit_date: string | null;
  source_username: string | null;
  salesman_sk: string | null;
  salesman_name: string | null;
  source_store_id: string | null;
  outlet_sk: string | null;
  store_name: string | null;
  distributor_code: string | null;
  brand_group: string | null;
  visit_status: string | null;
  effective_call: string | null;
  source_visit_type: string | null;
  notes: string | null;
  duration_minutes: number | null;
  checkin_time: string | null;
  checkout_time: string | null;
  item_count: number;
  computed_qty: number | null;
  computed_value: number | null;
  source_total_demand: number | null;
  total_mismatch: boolean;
  synced_at: string | null;
}

export interface ExtTransactionDetail extends ExtTransaction {
  items: ExtTransactionItem[];
}

export interface ExtTransactionSummary {
  transactions: number;
  total_quantity: number;
  total_value: number;
  unique_stores: number;
  unique_products: number;
  unmapped_stores: number;
}

export interface ExtTransactionListResponse {
  data: ExtTransaction[];
  pagination: {
    page: number;
    page_size: number;
    total: number;
    total_pages: number;
    has_next: boolean;
  };
  summary: ExtTransactionSummary;
  source_available: boolean;
}

export interface ExtSalesmanOption {
  salesman_sk: string | null;
  source_username: string | null;
  salesman_name: string | null;
  transactions: number;
}

// ── Notification ──────────────────────────────────────────────────────────────
export type NotificationType = "approval" | "announcement" | "compliance" | "target" | "system";

export interface Notification {
  notification_id: string;
  type: NotificationType;
  title: string;
  body: string;
  is_read: boolean;
  deep_link: string | null;
  created_at: string;
}

// ── Unified multi-source orders (Visit & Order) ───────────────────────────────
// SFA and the spreadsheet mirror normalized into one shape. `source` is always
// present so the table can label provenance without opening the detail view.
export type OrderSource = "SFA" | "SPREADSHEET";

export interface OrderRow {
  source: OrderSource;
  source_label: string;
  order_id: string;
  order_number: string | null;
  order_date: string | null;
  store_id: string | null;
  store_name: string | null;
  distributor_code: string | null;
  distributor_name: string | null;
  salesman_name: string | null;
  item_count: number;
  product_summary: string | null;
  quantity: number | null;
  order_value: number | null;
  status: string | null;
}

export interface OrderItemRow {
  source: OrderSource;
  order_id: string;
  order_number: string | null;
  sku: string | null;
  product_name: string | null;
  quantity: number | null;
  unit_price: number | null;
  line_value: number | null;
}

export interface OrderSourceStatus {
  source: OrderSource;
  label: string;
  ok: boolean;
  count: number;
  error: string | null;
}

export interface OrderListResponse {
  data: OrderRow[];
  pagination: { page: number; page_size: number; total: number; total_pages: number; has_next: boolean };
  summary: {
    total_orders: number;
    pending_orders: number;
    completed_orders: number;
    total_quantity: number;
    total_value: number;
  };
  sources: OrderSourceStatus[];
  truncated: boolean;
}
