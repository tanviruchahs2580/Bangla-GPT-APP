import type { ReactNode } from "react";
import { cn } from "../lib/cn";

// ResponsiveTable (D workstream, 2026-11-18): the shared data-table surface
// behind `.table-wrap` / `table.data` / `.cardable`. It consolidates the
// markup every bespoke table repeated — wrapper, header row with
// scope="col", per-cell data-labels for the cardable mobile fallback, stable
// row keys — WITHOUT changing the visual contract: the class names, the
// mobile card fallback and the state handling around the table are exactly
// what the migrated pages rendered before.
//
// Deliberately NOT part of this component (kept page-owned, preserving
// behaviour): data fetching, loading/error/empty composition (LoadError /
// EmptyState / Spinner stay at the call site — an error must never masquerade
// as an empty table), pagination, filtering, authorization. There is no sort
// support because no migrated surface sorts; add it with a real consumer,
// not speculatively.

export type TableColumn<T> = {
  /** Stable column id (React key + future a11y wiring). */
  id: string;
  /** Already-localized header content (callers pass t(...)). */
  header: ReactNode;
  /** Cell content for one row. */
  cell: (row: T) => ReactNode;
  /** Extra class for every body cell of this column (e.g. "cell-wrap-sm"). */
  cellClassName?: string;
  /**
   * data-label for the .cardable mobile fallback. Defaults to `header` when
   * the header is a plain string; pass it explicitly for dynamic headers.
   */
  mobileLabel?: string;
};

export function ResponsiveTable<T>({
  columns,
  rows,
  rowKey,
  caption,
  actions,
  actionsMobileLabel,
  cardable = false,
  emptyMessage,
  tbodyPrefix,
  tbodySuffix,
  rowHeader = false,
  className,
}: {
  columns: ReadonlyArray<TableColumn<T>>;
  rows: ReadonlyArray<T>;
  /** Stable key per row (identity, not array index, wherever possible). */
  rowKey: (row: T, index: number) => string;
  /** Accessible table caption (rendered as <caption>). */
  caption?: ReactNode;
  /** Trailing actions column; the header cell stays empty, as migrated pages had. */
  actions?: (row: T) => ReactNode;
  /** data-label for the actions cell in the cardable fallback. */
  actionsMobileLabel?: string;
  /**
   * Render the FIRST column's body cells as `<th scope="row">` instead of
   * `<td>` — for matrix tables whose rows are headed by a concept/class
   * label. Only the first column is affected.
   */
  rowHeader?: boolean;
  /** Opt into the ≤760px card fallback (same class the pages used). */
  cardable?: boolean;
  /**
   * Localized empty-state row. Only pass it where the page previously showed
   * a bare header-only table — an explicit empty row keeps "empty" distinct
   * from loading/error.
   */
  emptyMessage?: ReactNode;
  /**
   * Escape hatch for exceptional tbody rows some pages render before the
   * data rows (e.g. an inline error row with colSpan). Use sparingly.
   */
  tbodyPrefix?: ReactNode;
  /** Same escape hatch, for rows after the data rows (e.g. a summary row). */
  tbodySuffix?: ReactNode;
  className?: string;
}) {
  const colCount = columns.length + (actions ? 1 : 0);
  return (
    <div className={cn("table-wrap", className)}>
      <table className={cn("data", cardable && "cardable")}>
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.id} scope="col">
                {c.header}
              </th>
            ))}
            {actions ? <th scope="col"></th> : null}
          </tr>
        </thead>
        <tbody>
          {tbodyPrefix}
          {rows.length === 0 && emptyMessage ? (
            <tr>
              <td colSpan={colCount}>{emptyMessage}</td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr key={rowKey(row, i)}>
                {columns.map((c, colIdx) => {
                  const label =
                    c.mobileLabel ??
                    (typeof c.header === "string" ? c.header : undefined);
                  const content = c.cell(row);
                  if (rowHeader && colIdx === 0) {
                    return (
                      <th key={c.id} scope="row">
                        {content}
                      </th>
                    );
                  }
                  return (
                    <td
                      key={c.id}
                      data-label={
                        cardable && label !== undefined ? label : undefined
                      }
                      className={c.cellClassName}
                    >
                      {content}
                    </td>
                  );
                })}
                {actions ? (
                  <td
                    data-label={
                      cardable && actionsMobileLabel !== undefined
                        ? actionsMobileLabel
                        : undefined
                    }
                  >
                    {actions(row)}
                  </td>
                ) : null}
              </tr>
            ))
          )}
          {tbodySuffix}
        </tbody>
      </table>
    </div>
  );
}
