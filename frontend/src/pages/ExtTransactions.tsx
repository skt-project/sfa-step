import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import TopNav from "@/components/layout/TopNav";
import { Icon, SkeletonTable, SkeletonStatCards, EmptyState, Modal } from "@/components/ui";
import {
  listExtTransactions,
  listExtSalesmen,
  getExtTransaction,
} from "@/api/extTransaction";
import { useDebounce } from "@/hooks/useDebounce";
import type { ExtTransaction } from "@/types";

const PAGE_SIZE = 50;

const MONTHS_ID = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

/** Format a calendar date WITHOUT constructing a Date — a `visit_date` is a
 *  calendar day, not an instant, so it must never be timezone-shifted. */
function formatSourceDate(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  if (!y || !m || !d) return iso;
  return `${d} ${MONTHS_ID[Number(m) - 1] ?? m} ${y}`;
}

/** Timestamps ARE instants (stored UTC) — render them in the operating timezone. */
function formatSourceTime(iso: string | null): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toLocaleString("id-ID", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jakarta",
  });
}

const rp = (n: number | null | undefined) =>
  n == null ? "—" : `Rp ${Math.round(n).toLocaleString("id-ID")}`;

const num = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("id-ID", { maximumFractionDigits: 2 });

export default function ExtTransactions() {
  const [fromDate,   setFromDate]   = useState("");
  const [toDate,     setToDate]     = useState("");
  const [salesman,   setSalesman]   = useState("");
  const [storeQuery, setStoreQuery] = useState("");
  const [search,     setSearch]     = useState("");
  const [sortBy,     setSortBy]     = useState("visit_date");
  const [sortOrder,  setSortOrder]  = useState<"asc" | "desc">("desc");
  const [page,       setPage]       = useState(1);
  const [openId,     setOpenId]     = useState<string | null>(null);

  const debouncedStore  = useDebounce(storeQuery, 350);
  const debouncedSearch = useDebounce(search, 350);

  const filters = {
    from_date:   fromDate || undefined,
    to_date:     toDate || undefined,
    salesman_sk: salesman || undefined,
    store:       debouncedStore || undefined,
    search:      debouncedSearch || undefined,
    sort_by:     sortBy,
    sort_order:  sortOrder,
    page,
    page_size:   PAGE_SIZE,
  };

  const { data, isLoading, isFetching, isError } = useQuery({
    queryKey: ["ext-transactions", filters],
    queryFn: () => listExtTransactions(filters),
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });

  // Options come from the caller's own scoped transactions — the backend never
  // exposes another distributor's salesmen here.
  const { data: salesmen } = useQuery({
    queryKey: ["ext-salesmen", fromDate, toDate],
    queryFn: () => listExtSalesmen({ from_date: fromDate || undefined, to_date: toDate || undefined }),
    staleTime: 300_000,
  });

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ["ext-transaction", openId],
    queryFn: () => getExtTransaction(openId as string),
    enabled: !!openId,
  });

  const rows        = data?.data ?? [];
  const summary     = data?.summary;
  const pagination  = data?.pagination;
  const unavailable = isError || data?.source_available === false;

  const hasFilters = !!(fromDate || toDate || salesman || storeQuery || search);
  const resetFilters = () => {
    setFromDate(""); setToDate(""); setSalesman("");
    setStoreQuery(""); setSearch(""); setPage(1);
  };

  const toggleSort = (key: string) => {
    if (sortBy === key) {
      setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key);
      setSortOrder("desc");
    }
    setPage(1);
  };

  const SortHeader = ({ label, sortKey, align }: { label: string; sortKey: string; align?: "right" }) => (
    <th className={align === "right" ? "text-right" : undefined}>
      <button
        className="inline-flex items-center gap-1 hover:text-slate-700"
        onClick={() => toggleSort(sortKey)}
        aria-label={`Urutkan berdasarkan ${label}`}
      >
        {label}
        {sortBy === sortKey && (
          <Icon
            name={sortOrder === "asc" ? "arrow-trending-up" : "arrow-trending-down"}
            className="w-3 h-3"
          />
        )}
      </button>
    </th>
  );

  const tiles = [
    { label: "Transaksi",       value: summary ? summary.transactions.toLocaleString("id-ID") : "—", icon: "clipboard-document-list" as const, cls: "icon-badge-blue"   },
    { label: "Nilai Transaksi", value: summary ? rp(summary.total_value) : "—",                      icon: "currency-dollar"        as const, cls: "icon-badge-green"  },
    { label: "Kuantitas",       value: summary ? num(summary.total_quantity) : "—",                  icon: "table-cells"            as const, cls: "icon-badge-indigo" },
    { label: "Toko Unik",       value: summary ? summary.unique_stores.toLocaleString("id-ID") : "—", icon: "building-storefront"   as const, cls: "icon-badge-amber"  },
    { label: "Produk Unik",     value: summary ? summary.unique_products.toLocaleString("id-ID") : "—", icon: "tag"                 as const, cls: "icon-badge-purple" },
  ];

  return (
    <div className="flex flex-col h-full">
      <TopNav title="Transaction History" />

      <main className="flex-1 overflow-y-auto p-6 space-y-5">
        {/* Source provenance — these are NOT SFA visits, and the user must see that. */}
        <div className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5">
          <Icon name="information-circle" className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
          <p className="text-xs text-amber-900 leading-relaxed">
            <span className="font-semibold">Sumber data eksternal.</span>{" "}
            Transaksi di halaman ini berasal dari spreadsheet distributor, bukan dari
            transaksi SFA (Visit &amp; Order). Data bersifat baca-saja dan diperbarui
            saat sinkronisasi.
          </p>
        </div>

        {/* Summary */}
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

        {/* Filters */}
        <div className="filter-bar">
          <div className="search-bar w-60">
            <Icon name="search" />
            <input
              type="text"
              placeholder="Cari ID transaksi / SKU / produk..."
              aria-label="Cari transaksi"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            />
          </div>

          <div className="search-bar w-48">
            <Icon name="building-storefront" />
            <input
              type="text"
              placeholder="Cari toko..."
              aria-label="Cari nama toko"
              value={storeQuery}
              onChange={(e) => { setStoreQuery(e.target.value); setPage(1); }}
            />
          </div>

          <input
            type="date"
            className="input w-40"
            aria-label="Tanggal mulai"
            value={fromDate}
            onChange={(e) => { setFromDate(e.target.value); setPage(1); }}
          />
          <span className="text-xs text-slate-400">s/d</span>
          <input
            type="date"
            className="input w-40"
            aria-label="Tanggal akhir"
            value={toDate}
            onChange={(e) => { setToDate(e.target.value); setPage(1); }}
          />

          <select
            className="input w-52"
            aria-label="Filter salesman"
            value={salesman}
            onChange={(e) => { setSalesman(e.target.value); setPage(1); }}
          >
            <option value="">Semua Salesman</option>
            {(salesmen ?? []).map((s) => {
              const val = s.salesman_sk || s.source_username || "";
              return (
                <option key={val} value={val}>
                  {s.salesman_name || s.source_username} ({s.transactions})
                </option>
              );
            })}
          </select>

          {hasFilters && (
            <button className="btn-ghost btn-sm text-slate-400" onClick={resetFilters}>
              <Icon name="x-mark" className="w-3.5 h-3.5" />
              Reset
            </button>
          )}

          <div className="ml-auto flex items-center gap-2">
            {isFetching && <Icon name="arrow-path" className="w-4 h-4 text-slate-400 animate-spin" />}
            <span className="text-xs text-slate-400 tabular-nums">
              {pagination ? `${pagination.total.toLocaleString("id-ID")} transaksi` : ""}
            </span>
          </div>
        </div>

        {/* Table */}
        {isLoading ? (
          <SkeletonTable rows={8} cols={7} />
        ) : unavailable ? (
          <div className="table-container">
            <EmptyState
              icon="exclamation-triangle"
              title="Sumber transaksi sedang tidak tersedia"
              description="Silakan coba beberapa saat lagi. Jika berlanjut, hubungi administrator."
            />
          </div>
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <SortHeader label="Tanggal"  sortKey="visit_date" />
                  <SortHeader label="Salesman" sortKey="salesman" />
                  <SortHeader label="Toko"     sortKey="store" />
                  <SortHeader label="Item"     sortKey="items"    align="right" />
                  <SortHeader label="Qty"      sortKey="quantity" align="right" />
                  <SortHeader label="Nilai"    sortKey="value"    align="right" />
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={7}>
                      <EmptyState
                        icon="list-bullet"
                        title="Tidak ada transaksi untuk filter yang dipilih."
                        description={hasFilters ? "Coba ubah atau hapus filter yang aktif." : undefined}
                      />
                    </td>
                  </tr>
                ) : (
                  rows.map((t: ExtTransaction) => (
                    <tr
                      key={t.ext_visit_id}
                      className="cursor-pointer group"
                      tabIndex={0}
                      role="button"
                      aria-label={`Detail transaksi ${t.ext_visit_id}`}
                      onClick={() => setOpenId(t.ext_visit_id)}
                      onKeyDown={(e) => { if (e.key === "Enter") setOpenId(t.ext_visit_id); }}
                    >
                      <td className="text-slate-500 tabular-nums whitespace-nowrap">
                        {formatSourceDate(t.visit_date)}
                      </td>
                      <td className="font-medium text-slate-800">
                        {t.salesman_name ?? t.source_username ?? "—"}
                      </td>
                      <td className="text-slate-600 max-w-[220px] truncate">
                        {t.store_name ?? t.source_store_id ?? "—"}
                        {!t.outlet_sk && (
                          <span className="ml-1.5 badge-gray text-2xs" title="Toko ini belum terpetakan ke master STEP">
                            belum terpetakan
                          </span>
                        )}
                      </td>
                      <td className="text-right text-slate-500 tabular-nums">{t.item_count}</td>
                      <td className="text-right text-slate-500 tabular-nums">{num(t.computed_qty)}</td>
                      <td className="text-right font-medium text-slate-700 tabular-nums whitespace-nowrap">
                        {rp(t.computed_value)}
                        {t.total_mismatch && (
                          <Icon
                            name="exclamation-triangle"
                            className="w-3.5 h-3.5 text-amber-500 inline ml-1.5 -mt-0.5"
                          />
                        )}
                      </td>
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

        {/* Pagination */}
        {pagination && pagination.total > PAGE_SIZE && (
          <nav className="pagination" aria-label="Navigasi halaman">
            <span>{pagination.total.toLocaleString("id-ID")} transaksi total</span>
            <div className="flex items-center gap-2">
              <button
                className="pagination-btn"
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
                aria-label="Halaman sebelumnya"
              >
                <Icon name="chevron-left" className="w-4 h-4" aria-hidden={true} />
                Sebelumnya
              </button>
              <span className="text-xs text-slate-500 tabular-nums" aria-live="polite" aria-atomic="true">
                Hal. {pagination.page} / {Math.max(pagination.total_pages, 1)}
              </span>
              <button
                className="pagination-btn"
                disabled={!pagination.has_next}
                onClick={() => setPage((p) => p + 1)}
                aria-label="Halaman berikutnya"
              >
                Berikutnya
                <Icon name="chevron-right" className="w-4 h-4" aria-hidden={true} />
              </button>
            </div>
          </nav>
        )}
      </main>

      {/* Detail */}
      <Modal
        open={!!openId}
        onClose={() => setOpenId(null)}
        title="Detail Transaksi"
        maxWidth="2xl"
      >
        {detailLoading || !detail ? (
          <SkeletonTable rows={5} cols={4} />
        ) : (
          <div className="space-y-5">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
              <div>
                <dt className="kpi-tile-label">ID Transaksi</dt>
                <dd className="font-medium text-slate-800 break-all">{detail.ext_visit_id}</dd>
              </div>
              <div>
                <dt className="kpi-tile-label">Tanggal</dt>
                <dd className="font-medium text-slate-800">{formatSourceDate(detail.visit_date)}</dd>
              </div>
              <div>
                <dt className="kpi-tile-label">Salesman</dt>
                <dd className="font-medium text-slate-800">
                  {detail.salesman_name ?? detail.source_username ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="kpi-tile-label">Toko</dt>
                <dd className="font-medium text-slate-800">
                  {detail.store_name ?? detail.source_store_id ?? "—"}
                </dd>
              </div>
              {detail.checkin_time && (
                <div>
                  <dt className="kpi-tile-label">Check-in</dt>
                  <dd className="text-slate-600">{formatSourceTime(detail.checkin_time)}</dd>
                </div>
              )}
              {detail.checkout_time && (
                <div>
                  <dt className="kpi-tile-label">Check-out</dt>
                  <dd className="text-slate-600">{formatSourceTime(detail.checkout_time)}</dd>
                </div>
              )}
              {detail.visit_status && (
                <div>
                  <dt className="kpi-tile-label">Status</dt>
                  <dd><span className="badge-gray">{detail.visit_status}</span></dd>
                </div>
              )}
              {detail.notes && (
                <div className="col-span-2">
                  <dt className="kpi-tile-label">Catatan</dt>
                  <dd className="text-slate-600">{detail.notes}</dd>
                </div>
              )}
            </dl>

            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Produk
              </p>
              <div className="table-container">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Produk</th>
                      <th className="text-right">Qty</th>
                      <th className="text-right">Harga</th>
                      <th className="text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.items.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="text-center text-slate-400 text-sm py-6">
                          Tidak ada rincian produk untuk transaksi ini.
                        </td>
                      </tr>
                    ) : (
                      detail.items.map((it) => (
                        <tr key={it.ext_visit_item_id}>
                          <td className="text-slate-700">
                            {it.sku_name ?? it.sku_id ?? "—"}
                            {it.sku_name && it.sku_id && (
                              <span className="block text-2xs text-slate-400">{it.sku_id}</span>
                            )}
                          </td>
                          <td className="text-right tabular-nums text-slate-600">{num(it.qty)}</td>
                          <td className="text-right tabular-nums text-slate-600">{rp(it.stp)}</td>
                          <td className="text-right tabular-nums font-medium text-slate-700">
                            {rp(it.line_value)}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="flex justify-end gap-8 text-sm border-t border-slate-100 pt-3">
              <div className="text-right">
                <p className="kpi-tile-label">Total Kuantitas</p>
                <p className="font-semibold text-slate-800 tabular-nums">{num(detail.computed_qty)}</p>
              </div>
              <div className="text-right">
                <p className="kpi-tile-label">Total Nilai</p>
                <p className="font-semibold text-slate-800 tabular-nums">{rp(detail.computed_value)}</p>
              </div>
            </div>

            {detail.total_mismatch && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                <Icon name="exclamation-triangle" className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
                <p className="text-xs text-amber-900">
                  Total dari sumber ({rp(detail.source_total_demand)}) berbeda dengan jumlah
                  rincian produk ({rp(detail.computed_value)}). Nilai rincian yang ditampilkan;
                  nilai sumber tidak diubah.
                </p>
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
