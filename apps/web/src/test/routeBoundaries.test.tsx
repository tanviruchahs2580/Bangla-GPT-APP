/**
 * F-001: there was exactly one ErrorBoundary, at the root, with no reset key.
 * Any page-level render error replaced the whole app (nav included) and the
 * error state survived navigation — the only escape was a full reload.
 *
 * The fix gives the boundary a reset key tied to the route and wraps each
 * route with it, so a page error keeps the shell and navigation recovers.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { RouteErrorBoundary } from "../components/AppErrorBoundary";
import { t } from "../i18n";

function Bomb(): JSX.Element {
  throw new Error("render exploded");
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      {/* The shell's navigation lives outside the route boundary, exactly as
          AppShell wraps <RouteErrorBoundary> in the app. */}
      <nav>
        <Link to="/b">go-to-b</Link>
        <Link to="/a/2">go-to-a2</Link>
      </nav>
      <Routes>
        <Route
          path="/a/:id"
          element={
            <RouteErrorBoundary>
              <Bomb />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/a/2"
          element={
            <RouteErrorBoundary>
              <p>page-a2</p>
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/b"
          element={
            <RouteErrorBoundary>
              <p>page-b</p>
            </RouteErrorBoundary>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // React logs caught render errors; keep the test output clean.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("per-route error boundary (F-001)", () => {
  it("renders the boundary fallback when a page throws, keeping the shell", async () => {
    renderAt("/a/1");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(t("errorGeneric"));
    expect(
      screen.getByRole("button", { name: t("retry") }),
    ).toBeInTheDocument();
    // The shell (nav) did not disappear with the page.
    expect(screen.getByRole("link", { name: "go-to-b" })).toBeInTheDocument();
  });

  it("recovers when navigating to another route", async () => {
    const user = userEvent.setup();
    renderAt("/a/1");
    await screen.findByRole("alert");

    await user.click(screen.getByRole("link", { name: "go-to-b" }));

    expect(await screen.findByText("page-b")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("recovers when only the route params change (same route element)", async () => {
    // /a/1 and /a/2 share one Route element, so React reuses the boundary
    // instance — only the route-tied reset key can clear the error there.
    const user = userEvent.setup();
    renderAt("/a/1");
    await screen.findByRole("alert");

    await user.click(screen.getByRole("link", { name: "go-to-a2" }));

    expect(await screen.findByText("page-a2")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
