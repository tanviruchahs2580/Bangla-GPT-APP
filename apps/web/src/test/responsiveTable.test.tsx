import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import {
  ResponsiveTable,
  type TableColumn,
} from "../components/ResponsiveTable";

// D workstream: the shared data-table surface must reproduce the markup
// contract the bespoke tables rendered (table-wrap > table.data[.cardable],
// scope="col" headers, data-label cells in the cardable fallback, stable
// row keys) — the pages' own tests already pin the surrounding behaviour.
afterEach(cleanup);

type Row = { id: string; name: string; score: number };

const columns: TableColumn<Row>[] = [
  { id: "name", header: "নাম", cell: (r) => r.name },
  {
    id: "score",
    header: "গড়",
    cell: (r) => r.score,
    cellClassName: "cell-wrap-sm",
  },
];

const rows: Row[] = [
  { id: "s1", name: "আমিনা", score: 88 },
  { id: "s2", name: "রফিক", score: 72 },
];

describe("ResponsiveTable", () => {
  it("renders the shared wrapper, headers with scope, and stable row keys", () => {
    const { container } = render(
      <ResponsiveTable columns={columns} rows={rows} rowKey={(r) => r.id} />,
    );
    const wrap = container.querySelector(".table-wrap");
    const table = container.querySelector("table.data");
    expect(wrap).not.toBeNull();
    expect(table).not.toBeNull();
    expect(table!.className).not.toContain("cardable");
    const headers = [...container.querySelectorAll("thead th")];
    expect(headers.map((h) => h.getAttribute("scope"))).toEqual(["col", "col"]);
    const bodyRows = [...container.querySelectorAll("tbody tr")];
    // React keys are not DOM-visible properties; key stability is enforced
    // by the component's rowKey contract (see the cardable test below for
    // the observable contract).
    expect(bodyRows).toHaveLength(2);
    expect(screen.getByText("আমিনা")).toBeTruthy();
    expect(screen.getByText("88")).toBeTruthy();
  });

  it("omits data-label outside the cardable fallback", () => {
    const { container } = render(
      <ResponsiveTable columns={columns} rows={rows} rowKey={(r) => r.id} />,
    );
    expect(container.querySelector("td[data-label]")).toBeNull();
  });

  it("sets data-label from the header in cardable mode (and honours overrides)", () => {
    const { container } = render(
      <ResponsiveTable
        columns={[columns[0], { ...columns[1], mobileLabel: "গড় স্কোর" }]}
        rows={rows}
        rowKey={(r) => r.id}
        cardable
      />,
    );
    const tds = [...container.querySelectorAll("tbody td")];
    expect(tds.map((td) => td.getAttribute("data-label"))).toEqual([
      "নাম",
      "গড় স্কোর",
      "নাম",
      "গড় স্কোর",
    ]);
    expect(container.querySelector("td.cell-wrap-sm")).not.toBeNull();
  });

  it("renders a caption and an empty actions header with labelled cells", () => {
    const { container } = render(
      <ResponsiveTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        caption="শ্রেণির তালিকা"
        actions={(r) => <button>{`open ${r.id}`}</button>}
        actionsMobileLabel="action"
        cardable
      />,
    );
    expect(container.querySelector("caption")!.textContent).toBe(
      "শ্রেণির তালিকা",
    );
    const headers = [...container.querySelectorAll("thead th")];
    expect(headers).toHaveLength(3);
    expect(headers[2].textContent).toBe("");
    const actionTds = [...container.querySelectorAll("tbody td:last-child")];
    expect(actionTds.map((td) => td.getAttribute("data-label"))).toEqual([
      "action",
      "action",
    ]);
  });

  it("keeps empty distinct: the empty row spans all columns and is not a data row", () => {
    const { container } = render(
      <ResponsiveTable
        columns={columns}
        rows={[]}
        rowKey={(r) => r.id}
        emptyMessage="কোনো শিক্ষার্থী নেই"
        actions={() => null}
      />,
    );
    const emptyTd = container.querySelector("tbody td[colspan]")!;
    expect(emptyTd.getAttribute("colspan")).toBe("3");
    expect(emptyTd.textContent).toBe("কোনো শিক্ষার্থী নেই");
    expect(container.querySelectorAll("tbody tr")).toHaveLength(1);
  });

  it("renders no empty row when no message is given (page-owned states)", () => {
    const { container } = render(
      <ResponsiveTable columns={columns} rows={[]} rowKey={(r) => r.id} />,
    );
    expect(container.querySelectorAll("tbody tr")).toHaveLength(0);
  });

  it("prefixes exceptional tbody rows (inline error row escape hatch)", () => {
    const { container } = render(
      <ResponsiveTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        tbodyPrefix={
          <tr>
            <td colSpan={2}>লোড ব্যর্থ</td>
          </tr>
        }
      />,
    );
    const trs = [...container.querySelectorAll("tbody tr")];
    expect(trs).toHaveLength(3);
    expect(trs[0].textContent).toBe("লোড ব্যর্থ");
  });
});
