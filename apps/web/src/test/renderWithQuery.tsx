/**
 * Shared render helper for tests that mount pages reading the shared query
 * cache (audit H-04: the teacher pages moved to react-query, so every test
 * rendering one needs a QueryClientProvider). A FRESH client per render keeps
 * tests isolated; retry is off so a mocked failure surfaces immediately.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

export function renderWithQuery(
  ui: ReactElement,
  { route = "/", path }: { route?: string; path?: string } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      {path ? (
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={ui} />
          </Routes>
        </MemoryRouter>
      ) : (
        <MemoryRouter>{ui}</MemoryRouter>
      )}
    </QueryClientProvider>,
  );
}
