"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight, ChevronsUpDown, Search } from "lucide-react";
import {
  type ColumnDef,
  type ColumnFiltersState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  type PaginationState,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";

type InventoryDataTableProps<TData> = {
  columns: ColumnDef<TData, unknown>[];
  data: TData[];
  searchPlaceholder?: string;
  filterColumn?: string;
  emptyMessage?: string;
  errorMessage?: string;
  loading?: boolean;
  remote?: {
    total: number;
    query: string;
    page: number;
    pageSize: number;
    onQueryChange: (value: string) => void;
    onPageChange: (page: number) => void;
    onPageSizeChange: (size: number) => void;
    onSortChange?: (column: string, direction: "asc" | "desc") => void;
  };
};

export function InventoryDataTable<TData>({
  columns,
  data,
  searchPlaceholder = "Search inventory…",
  filterColumn,
  emptyMessage = "No inventory records match the current filters.",
  errorMessage,
  loading = false,
  remote,
}: InventoryDataTableProps<TData>) {
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 16 });
  const effectivePagination = remote ? { pageIndex: remote.page, pageSize: remote.pageSize } : pagination;
  // TanStack Table intentionally returns a stateful API that React Compiler
  // cannot memoize. Skipping compiler memoization for this hook is expected.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    state: { sorting, columnFilters, pagination: effectivePagination },
    onSortingChange: (updater) => {
      const next = typeof updater === "function" ? updater(sorting) : updater;
      setSorting(next);
      const first = next[0];
      if (first) remote?.onSortChange?.(first.id, first.desc ? "desc" : "asc");
    },
    onColumnFiltersChange: setColumnFilters,
    onPaginationChange: remote ? (updater) => {
      const next = typeof updater === "function" ? updater(effectivePagination) : updater;
      if (next.pageSize !== remote.pageSize) remote.onPageSizeChange(next.pageSize);
      else remote.onPageChange(next.pageIndex);
    } : setPagination,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualPagination: Boolean(remote),
    manualFiltering: Boolean(remote),
    manualSorting: Boolean(remote),
    rowCount: remote?.total,
  });

  const visibleRows = table.getRowModel().rows;
  const total = remote?.total ?? table.getFilteredRowModel().rows.length;
  const searchValue = remote?.query ?? ((table.getColumn(filterColumn ?? "")?.getFilterValue() as string) ?? "");

  return (
    <div className="overflow-hidden rounded-2xl border border-border/70 bg-card shadow-sm">
      <div className="flex flex-col gap-3 border-b border-border/70 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <label className="relative block max-w-sm flex-1">
          <span className="sr-only">{searchPlaceholder.replace(/…$/, "")}</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            className="h-9 w-full rounded-lg border border-border bg-background pl-9 pr-3 text-sm outline-none transition focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
            placeholder={searchPlaceholder}
            value={searchValue}
            onChange={(event) => remote ? remote.onQueryChange(event.target.value) : table.getColumn(filterColumn ?? "")?.setFilterValue(event.target.value)}
          />
        </label>
        <span className="font-mono text-xs text-muted-foreground">{total.toLocaleString()} records</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[840px] text-left text-sm">
          <thead className="bg-muted/45 text-xs uppercase tracking-[0.12em] text-muted-foreground">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id} className="h-11 px-4 font-medium" aria-sort={header.column.getIsSorted() === "asc" ? "ascending" : header.column.getIsSorted() === "desc" ? "descending" : undefined}>
                    {header.isPlaceholder ? null : (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 transition hover:text-foreground disabled:cursor-default"
                        disabled={!header.column.getCanSort()}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {header.column.getCanSort() ? <ChevronsUpDown className="size-3.5 opacity-55" /> : null}
                      </button>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-border/60">
            {visibleRows.length ? visibleRows.map((row) => (
              <tr key={row.id} className="transition-colors hover:bg-muted/35">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-4 py-3 align-middle">{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            )) : (
              <tr><td colSpan={columns.length} className="px-4 py-12 text-center text-muted-foreground">{loading ? "Loading inventory…" : errorMessage ? <span role="alert" className="text-destructive">{errorMessage}</span> : emptyMessage}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex flex-col gap-3 border-t border-border/70 px-4 py-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">Rows <select aria-label="Rows per page" className="rounded-md border border-border bg-background px-2 py-1 text-foreground" value={effectivePagination.pageSize} onChange={(e) => table.setPageSize(Number(e.target.value))}>{[8, 16, 32].map((size) => <option key={size}>{size}</option>)}</select></div>
        <div className="flex items-center gap-2"><span>{visibleRows.length ? `${effectivePagination.pageIndex * effectivePagination.pageSize + 1}–${Math.min(effectivePagination.pageIndex * effectivePagination.pageSize + visibleRows.length, total)} of ${total}` : "0 records"}</span><button aria-label="Previous page" className="rounded-md border border-border p-1 disabled:opacity-40" onClick={() => table.previousPage()} disabled={loading || !table.getCanPreviousPage()}><ChevronLeft className="size-4" /></button><button aria-label="Next page" className="rounded-md border border-border p-1 disabled:opacity-40" onClick={() => table.nextPage()} disabled={loading || !table.getCanNextPage()}><ChevronRight className="size-4" /></button></div>
      </div>
    </div>
  );
}
