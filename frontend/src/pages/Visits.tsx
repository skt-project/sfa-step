import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import TopNav from "@/components/layout/TopNav";
import { Icon, SkeletonTable, SkeletonStatCards, EmptyState, Modal } from "@/components/ui";
import { listOrders, getOrderDetail, exportOrders, exportSingleOrder, updateOrderAdjustment, type OrderFilters } from "@/api/orders";
import { useDebounce } from "@/hooks/useDebounce";
import { useAuthStore } from "@/store/authStore";
import { toast } from "@/store/toastStore";
import type { OrderRow, OrderSource, VisitApprovalStatus } from "@/types";

const PAGE_SIZE = 50;

const APPROVAL_STATUS_MAP: Record<string, { label: string; cls: string }> = {
  DRAFT:             { label: "Draft",         cls: "badge-gray"   },
  SUBMITTED:         { label: "Submitted",     cls: "badge-yellow" },
  PENDING_SPV:       { label: "Menunggu SPV",  cls: "badge-yellow" },
  SPV_APPROVED:      { label: "SPV Approved",  cls: "badge-blue"   },
  ASM_APPROVED:      { label: "ASM Approved",  cls: "badge-blue"   },
  DDM_APPROVED:      { label: "DDM Approved",  cls: "badge-blue"   },
  REVISION_REQUIRED: { label: "Perlu Revisi",  cls: "badge-red"    },
  COMPLETED:         { label: "Selesai",       cls: "badge-green"  },
  REJECTED:          { label: "Ditolak",       cls: "badge-red"    },
};

function StatusBadge({ status }: { status: string | null }) {
  const s = (status ?? "DRAFT") as VisitApprovalStatus;
  const { label, cls } = APPROVAL_STATUS_MAP[s] ?? { label: status ?? "—", cls: "badge-gray" };
  return <span className={cls}>{label}</span>;
}

/** Provenance is visible in the table itself — the user never has to open a row
 *  just to find out where an order came from. */
function SourceBadge({ source, label }: { source: OrderSource; label: string }) {
  const cls = source === "SFA" ? "badge-blue" : "badge-purple";
  return <span className={cls} title={label}>{source === "SFA" ? "SFA" : "Spreadsheet"}</span>;
}

const SOURCE_OPTIONS: { value: string; label: string }[] = [
  { value: "ALL",         label: "Semua Sumber" },
  { value: "SFA",         label: "STEP Handheld / SFA" },
  { value: "SPREADSHEET", label: "Spreadsheet" },
];

const MONTHS_ID = ["Jan","Feb","Mar","Apr","Mei","Jun","Jul","Agu","Sep","Okt","Nov","Des"];

/** Format a calendar date without constructing a Date — an order date is a
 *  calendar day, not an instant, and must never be timezone-shifted. */
function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return iso;
  return `${d} ${MONTHS_ID[Number(m) - 1] ?? m} ${y}`;
}

const rp = (n: number | null | undefined) =>
  n == null ? "—" : `Rp ${Math.round(n).toLocaleString("id-ID")}`;
const num = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("id-ID", { maximumFractionDigits: 2 });

type TabKey = "waiting" | "all";

export default function Visits() {
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [tab,         setTab]         = useState<TabKey>("waiting");
  const [source,      setSource]      = useState("ALL");
  const [dateFrom,    setDateFrom]    = useState("");
  const [dateTo,      setDateTo]      = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [storeSearch, setStoreSearch] = useState("");
  const [skuSearch,   setSkuSearch]   = useState("");
  const [search,      setSearch]      = useState("");
  const [page,        setPage]        = useState(1);
  const [openRow,     setOpenRow]     = useState<OrderRow | null>(null);
  const [exporting,   setExporting]   = useState(false);
  const [rowExporting, setRowExporting] = useState(false);
  const [adjEditing,  setAdjEditing]  = useState(false);
  const [adjAmount,   setAdjAmount]   = useState(0);
  const [adjNote,     setAdjNote]     = useState("");

  const dStore  = useDebounce(storeSearch, 350);
  const dSku    = useDebounce(skuSearch, 350);
  const dSearch = useDebounce(search, 350);

  // Distributor accounts have no "waiting" queue tab: a dm's orders arrive
  // already SPV_APPROVED/COMPLETED, and defaulting to a narrow status filter
  // produced a page that looked broken whenever nothing matched it (indistinguishable
  // from an actual failure). Distributors always see everything, filterable manually.
  const role          = useAuthStore((s) => s.user?.role);
  const isDistributor = role === "dm";
  const tabs: { key: TabKey; label: string }[] = [
    { key: "waiting", label: "Menunggu SPV" },
    { key: "all",     label: "Semua Order" },
  ];

  const activeStatus = !isDistributor && tab === "waiting" && !statusFilter
    ? "PENDING_SPV"
    : statusFilter || undefined;

  const filters: OrderFilters = {
    from_date:    dateFrom || undefined,
    to_date:      dateTo || undefined,
    source,
    status:       activeStatus,
    store:        dStore || undefined,
    sku:          dSku || undefined,
    search:       dSearch || undefined,
    page,
    page_size:    PAGE_SIZE,
  };

  const { data, isLoading, isFetching, isError, dataUpdatedAt } = useQuery({
    queryKey: ["orders", filters],
    queryFn: () => listOrders(filters),
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });

  const rows       = data?.data ?? [];
  const summary    = data?.summary;
  const pagination = data?.pagination;
  const failed     = (data?.sources ?? []).filter((s) => !s.ok);

  const hasFilters = !!(dateFrom || dateTo || statusFilter || storeSearch || skuSearch || search || source !== "ALL");
  const resetFilters = () => {
    setDateFrom(""); setDateTo(""); setStatusFilter(""); setStoreSearch("");
    setSkuSearch(""); setSearch(""); setSource("ALL"); setPage(1);
  };

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ["order-detail", openRow?.source, openRow?.order_id],
    queryFn: () => getOrderDetail(openRow!.source, openRow!.order_id),
    enabled: !!openRow,
  });

  // Same capability SFA orders already have (PUT /visit/{id}/adjustment) —
  // extended to Spreadsheet orders. Only the header-level adjustment is
  // editable; the synced quantities/prices stay a read-only mirror of the source.
  const isDistAdm = role === "dm" || role === "ho_admin";

  useEffect(() => {
    setAdjEditing(false);
    setAdjAmount(detail?.order?.adjustment_amount ?? 0);
    setAdjNote(detail?.order?.adjustment_note ?? "");
  }, [detail?.order?.order_id, detail?.order?.adjustment_amount, detail?.order?.adjustment_note]);

  const adjustMut = useMutation({
    mutationFn: () => updateOrderAdjustment(openRow!.order_id, adjAmount, adjNote.trim() || null),
    onSuccess: () => {
      setAdjEditing(false);
      qc.invalidateQueries({ queryKey: ["order-detail", "SPREADSHEET", openRow?.order_id] });
      qc.invalidateQueries({ queryKey: ["orders"] });
      toast.success("Penyesuaian tersimpan.");
    },
    onError: () => toast.error("Gagal menyimpan penyesuaian. Coba lagi."),
  });

  const openOrder = (o: OrderRow) => {
    // SFA orders keep their existing full detail page (approvals, PDF, items).
    if (o.source === "SFA") navigate(`/visits/${o.order_id}`);
    else setOpenRow(o);
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      // Same filters as the list, minus paging: the workbook is the whole
      // filtered set, not just the visible page.
      const { page: _p, page_size: _ps, ...rest } = filters;
      await exportOrders(rest);
      toast.success("Excel berhasil diunduh.");
    } catch {
      toast.error("Gagal mengunduh Excel. Silakan coba lagi.");
    } finally {
      setExporting(false);
    }
  };

  const handleRowExport = async () => {
    if (!openRow) return;
    setRowExporting(true);
    try {
      await exportSingleOrder(openRow.source, openRow.order_id);
      toast.success("Excel berhasil diunduh.");
    } catch {
      toast.error("Gagal mengunduh Excel. Silakan coba lagi.");
    } finally {
      setRowExporting(false);
    }
  };

  const tiles = [
    { label: "Total Order",  value: summary ? summary.total_orders.toLocaleString("id-ID") : "—",     icon: "clipboard-document-list" as const, cls: "icon-badge-blue"   },
    { label: "Pending",      value: summary ? summary.pending_orders.toLocaleString("id-ID") : "—",   icon: "clock"                   as const, cls: "icon-badge-amber"  },
    { label: "Selesai",      value: summary ? summary.completed_orders.toLocaleString("id-ID") : "—", icon: "check-circle"            as const, cls: "icon-badge-green"  },
    { label: "Total Qty",    value: summary ? num(summary.total_quantity) : "—",                      icon: "table-cells"             as const, cls: "icon-badge-indigo" },
    { label: "Total Nilai",  value: summary ? rp(summary.total_value) : "—",                          icon: "currency-dollar"         as const, cls: "icon-badge-purple" },
  ];

  return (
    <div className="flex flex-col h-full">
      <TopNav
        title="Visit & Order"
        actions={
          <button
            className="btn-secondary text-sm flex items-center gap-1.5"
            onClick={handleExport}
            disabled={exporting || isLoading}
          >
            <Icon name={exporting ? "arrow-path" : "arrow-down-tray"}
                  className={`w-4 h-4 ${exporting ? "animate-spin" : ""}`} />
            {exporting ? "Menyiapkan..." : "Export Excel"}
          </button>
        }
      />

      <main className="flex-1 overflow-y-auto">
        {/* ── Tabs (spv/asm/ho_admin only — a Distributor always sees everything) ── */}
        {!isDistributor && (
          <div className="tabs px-6" role="tablist" aria-label="Filter order">
            {tabs.map(({ key, label }) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => { setTab(key); setStatusFilter(""); setPage(1); }}
                className={`tab ${tab === key ? "tab-active" : ""}`}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        <div className="p-6 space-y-5">
          {/* ── Per-source failures: one source down never hides the others ── */}
          {failed.map((s) => (
            <div key={s.source}
                 className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5">
              <Icon name="exclamation-triangle" className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
              <p className="text-xs text-amber-900 leading-relaxed">
                <span className="font-semibold">{s.error}</span>{" "}
                Sumber lain tetap ditampilkan di bawah.
              </p>
            </div>
          ))}

          {data?.truncated && (
            <div className="flex items-start gap-2.5 rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-2.5">
              <Icon name="information-circle" className="w-4 h-4 text-slate-500 mt-0.5 shrink-0" />
              <p className="text-xs text-slate-600">
                Hasil dibatasi. Persempit filter atau rentang tanggal untuk melihat seluruh data.
              </p>
            </div>
          )}

          {/* ── Summary ── */}
          {isLoading ? (
            <SkeletonStatCards count={5} />
          ) : (
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
              {tiles.map((c) => (
                <div key={c.label} className="kpi-tile">
                  <span className={`icon-badge ${c.cls}`}>
                    <Icon name={c.icon} className="w-4 h-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="kpi-tile-value truncate">{c.value}</p>
                    <p className="kpi-tile-label">{c.label}</p>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ── Source selector ── */}
          <div className="flex gap-1 flex-wrap" role="group" aria-label="Filter sumber data">
            {SOURCE_OPTIONS.map((o) => (
              <button
                key={o.value}
                onClick={() => { setSource(o.value); setPage(1); }}
                className={`chip ${source === o.value ? "chip-active" : ""}`}
                aria-pressed={source === o.value}
              >
                {o.label}
              </button>
            ))}
          </div>

          {/* ── Filters ── */}
          <div className="filter-bar">
            <div className="search-bar w-56">
              <Icon name="search" />
              <input type="text" placeholder="Cari order / toko / SKU..." aria-label="Cari order"
                     value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
            </div>
            <div className="search-bar w-44">
              <Icon name="building-storefront" />
              <input type="text" placeholder="Toko..." aria-label="Filter toko"
                     value={storeSearch} onChange={(e) => { setStoreSearch(e.target.value); setPage(1); }} />
            </div>
            <div className="search-bar w-40">
              <Icon name="tag" />
              <input type="text" placeholder="SKU / produk..." aria-label="Filter SKU atau produk"
                     value={skuSearch} onChange={(e) => { setSkuSearch(e.target.value); setPage(1); }} />
            </div>
            <input type="date" className="input w-36" aria-label="Tanggal mulai"
                   value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1); }} />
            <span className="text-xs text-slate-400">s/d</span>
            <input type="date" className="input w-36" aria-label="Tanggal akhir"
                   value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1); }} />

            {(isDistributor || tab === "all") && (
              <select className="input w-44" aria-label="Filter status order"
                      value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
                <option value="">Semua Status</option>
                {Object.entries(APPROVAL_STATUS_MAP).map(([v, m]) => (
                  <option key={v} value={v}>{m.label}</option>
                ))}
              </select>
            )}

            {hasFilters && (
              <button className="btn-ghost btn-sm text-slate-400" onClick={resetFilters}>
                <Icon name="x-mark" className="w-3.5 h-3.5" /> Reset
              </button>
            )}

            <div className="ml-auto flex items-center gap-2">
              <button
                className="btn-ghost btn-sm text-slate-400"
                onClick={() => qc.invalidateQueries({ queryKey: ["orders"] })}
                aria-label="Muat ulang data"
              >
                <Icon name="arrow-path" className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} />
                Refresh
              </button>
              {dataUpdatedAt > 0 && (
                <span className="text-xs text-slate-400">
                  Diperbarui {new Date(dataUpdatedAt).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })}
                </span>
              )}
              <span className="text-xs text-slate-400 tabular-nums">
                {pagination ? `${pagination.total.toLocaleString("id-ID")} order` : ""}
              </span>
            </div>
          </div>

          {/* ── Table ── */}
          {isLoading ? (
            <SkeletonTable rows={8} cols={9} />
          ) : isError ? (
            <div className="table-container">
              <EmptyState icon="exclamation-triangle"
                          title="Data order tidak dapat dimuat"
                          description="Silakan coba beberapa saat lagi." />
            </div>
          ) : (
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>No. Order</th>
                    <th>Tanggal</th>
                    <th>Toko</th>
                    <th>Produk / SKU</th>
                    <th className="text-right">Qty</th>
                    <th className="text-right">Nilai</th>
                    <th>Status</th>
                    <th>Sumber</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 ? (
                    <tr>
                      <td colSpan={9}>
                        <EmptyState
                          icon="list-bullet"
                          title="Tidak ada order untuk filter yang dipilih."
                          description={hasFilters ? "Coba ubah atau hapus filter yang aktif." : undefined}
                        />
                      </td>
                    </tr>
                  ) : (
                    rows.map((o) => (
                      <tr key={`${o.source}:${o.order_id}`}
                          className="cursor-pointer group"
                          tabIndex={0}
                          role="button"
                          aria-label={`Detail order ${o.order_number ?? o.order_id}`}
                          onClick={() => openOrder(o)}
                          onKeyDown={(e) => { if (e.key === "Enter") openOrder(o); }}>
                        <td className="font-medium text-slate-800 max-w-[160px] truncate">
                          {o.order_number ?? o.order_id}
                        </td>
                        <td className="text-slate-500 tabular-nums whitespace-nowrap">{formatDate(o.order_date)}</td>
                        <td className="text-slate-600 max-w-[180px] truncate">
                          {o.store_name ?? o.store_id ?? "—"}
                        </td>
                        <td className="text-slate-600 max-w-[180px] truncate">
                          {o.product_summary ?? "—"}
                        </td>
                        <td className="text-right text-slate-500 tabular-nums">{num(o.quantity)}</td>
                        <td className="text-right font-medium text-slate-700 tabular-nums whitespace-nowrap">
                          {rp(o.order_value)}
                        </td>
                        <td><StatusBadge status={o.status} /></td>
                        <td><SourceBadge source={o.source} label={o.source_label} /></td>
                        <td>
                          <Icon name="chevron-right" className="w-4 h-4 text-slate-300 group-hover:text-primary-600" />
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* ── Pagination ── */}
          {pagination && pagination.total > PAGE_SIZE && (
            <nav className="pagination" aria-label="Navigasi halaman">
              <span>{pagination.total.toLocaleString("id-ID")} order total</span>
              <div className="flex items-center gap-2">
                <button className="pagination-btn" disabled={page === 1}
                        onClick={() => setPage((p) => p - 1)} aria-label="Halaman sebelumnya">
                  <Icon name="chevron-left" className="w-4 h-4" aria-hidden={true} /> Sebelumnya
                </button>
                <span className="text-xs text-slate-500 tabular-nums" aria-live="polite" aria-atomic="true">
                  Hal. {pagination.page} / {Math.max(pagination.total_pages, 1)}
                </span>
                <button className="pagination-btn" disabled={!pagination.has_next}
                        onClick={() => setPage((p) => p + 1)} aria-label="Halaman berikutnya">
                  Berikutnya <Icon name="chevron-right" className="w-4 h-4" aria-hidden={true} />
                </button>
              </div>
            </nav>
          )}
        </div>
      </main>

      {/* ── Spreadsheet order detail (SFA keeps its own full page) ── */}
      <Modal
        open={!!openRow}
        onClose={() => setOpenRow(null)}
        title="Detail Order"
        maxWidth="2xl"
        footer={
          <button
            className="btn-secondary btn-sm"
            onClick={handleRowExport}
            disabled={rowExporting || detailLoading || !detail?.order}
          >
            <Icon name={rowExporting ? "arrow-path" : "arrow-down-tray"}
                  className={`w-4 h-4 ${rowExporting ? "animate-spin" : ""}`} />
            {rowExporting ? "Menyiapkan..." : "Export Excel"}
          </button>
        }
      >
        {detailLoading || !detail?.order ? (
          <SkeletonTable rows={4} cols={4} />
        ) : (
          <div className="space-y-5">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <div><dt className="kpi-tile-label">No. Order</dt>
                   <dd className="font-medium text-slate-800 break-all">{detail.order.order_number ?? "—"}</dd></div>
              <div><dt className="kpi-tile-label">Tanggal</dt>
                   <dd className="font-medium text-slate-800">{formatDate(detail.order.order_date)}</dd></div>
              <div><dt className="kpi-tile-label">Toko</dt>
                   <dd className="font-medium text-slate-800">{detail.order.store_name ?? detail.order.store_id ?? "—"}</dd></div>
              <div><dt className="kpi-tile-label">Distributor</dt>
                   <dd className="font-medium text-slate-800">
                     {detail.order.distributor_name ?? detail.order.distributor_code ?? "—"}
                   </dd></div>
              <div><dt className="kpi-tile-label">Status</dt><dd><StatusBadge status={detail.order.status} /></dd></div>
              <div><dt className="kpi-tile-label">Sumber</dt>
                   <dd><SourceBadge source={detail.order.source} label={detail.order.source_label} /></dd></div>
            </dl>

            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Produk</p>
              <div className="table-container">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Produk</th><th>SKU</th>
                      <th className="text-right">Qty</th>
                      <th className="text-right">Harga</th>
                      <th className="text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.items.length === 0 ? (
                      <tr><td colSpan={5} className="text-center text-slate-400 text-sm py-6">
                        Tidak ada rincian produk untuk order ini.
                      </td></tr>
                    ) : detail.items.map((it, i) => (
                      <tr key={`${it.order_id}:${it.sku ?? i}`}>
                        <td className="text-slate-700">{it.product_name ?? "—"}</td>
                        <td className="text-slate-500">{it.sku ?? "—"}</td>
                        <td className="text-right tabular-nums text-slate-600">{num(it.quantity)}</td>
                        <td className="text-right tabular-nums text-slate-600">{rp(it.unit_price)}</td>
                        <td className="text-right tabular-nums font-medium text-slate-700">{rp(it.line_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* ── Distributor Admin invoice adjustment — same capability SFA
                   orders already have, extended to Spreadsheet orders. Only the
                   header-level adjustment is editable; synced quantities/prices
                   stay a read-only mirror of the source spreadsheet. ── */}
            {isDistAdm && (
              <div className="border-t border-slate-100 pt-3">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                    Penyesuaian Invoice
                  </p>
                  {!adjEditing && (
                    <button className="btn-secondary btn-sm" onClick={() => setAdjEditing(true)}>
                      <Icon name="pencil" className="w-3.5 h-3.5" />
                      {(detail.order.adjustment_amount ?? 0) !== 0 ? "Ubah" : "Tambah"}
                    </button>
                  )}
                </div>

                {adjEditing ? (
                  <div className="space-y-2">
                    <div>
                      <label className="text-xs text-slate-500 mb-1 block">
                        Nominal penyesuaian (Rp) — gunakan minus untuk pengurangan
                      </label>
                      <input
                        type="number" className="input text-sm tabular-nums w-full"
                        value={adjAmount || ""} placeholder="0" aria-label="Nominal penyesuaian"
                        onChange={(e) => setAdjAmount(parseFloat(e.target.value) || 0)}
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-500 mb-1 block">Keterangan</label>
                      <input
                        type="text" className="input text-sm w-full" value={adjNote}
                        placeholder="mis. Ongkos kirim / Diskon promo" aria-label="Keterangan penyesuaian"
                        onChange={(e) => setAdjNote(e.target.value)}
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        className="btn-primary btn-sm flex-1"
                        disabled={adjustMut.isPending}
                        onClick={() => adjustMut.mutate()}
                      >
                        {adjustMut.isPending ? "Menyimpan..." : "Simpan"}
                      </button>
                      <button
                        className="btn-secondary btn-sm flex-1"
                        onClick={() => {
                          setAdjEditing(false);
                          setAdjAmount(detail?.order?.adjustment_amount ?? 0);
                          setAdjNote(detail?.order?.adjustment_note ?? "");
                        }}
                      >
                        Batal
                      </button>
                    </div>
                  </div>
                ) : (detail.order.adjustment_amount ?? 0) !== 0 ? (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-500 truncate">
                      {detail.order.adjustment_note || "Penyesuaian"}
                    </span>
                    <span className={`font-medium tabular-nums ${
                      (detail.order.adjustment_amount ?? 0) < 0 ? "text-red-600" : "text-amber-600"
                    }`}>
                      {(detail.order.adjustment_amount ?? 0) > 0 ? "+ " : "− "}
                      {rp(Math.abs(detail.order.adjustment_amount ?? 0))}
                    </span>
                  </div>
                ) : (
                  <p className="text-xs text-slate-400">Tidak ada penyesuaian.</p>
                )}
              </div>
            )}

            <div className="flex justify-end gap-8 text-sm border-t border-slate-100 pt-3">
              <div className="text-right">
                <p className="kpi-tile-label">Total Qty</p>
                <p className="font-semibold text-slate-800 tabular-nums">{num(detail.order.quantity)}</p>
              </div>
              <div className="text-right">
                <p className="kpi-tile-label">Total Nilai</p>
                <p className="font-semibold text-slate-800 tabular-nums">
                  {rp((detail.order.order_value ?? 0) + (detail.order.adjustment_amount ?? 0))}
                </p>
              </div>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
