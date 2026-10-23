/**
 * Study mutations must invalidate the caches their results feed.
 *
 * The audited defect: with `staleTime: 30_000` and no invalidation, finishing
 * a quiz left the practice hub (and Home within the window) showing the
 * PRE-quiz average and streak, and a chapter read to 100% kept its
 * "reading" badge. `invalidateStudyCaches` is the single call every study
 * mutation now makes; this test drives it against a real QueryClient and
 * asserts both effects it must have — the active observer refetches, and
 * unobserved (but cached) study keys are left invalidated so the next mount
 * re-reads them.
 */

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { invalidateStudyCaches } from "../lib/invalidate";

function makeWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("invalidateStudyCaches", () => {
  it("refetches an active study query and leaves cached study keys stale", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { staleTime: 30_000, retry: false } },
    });
    let progressFetches = 0;

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ["progress", 5],
          queryFn: async () => {
            progressFetches += 1;
            return progressFetches;
          },
        }),
      { wrapper: makeWrapper(client) },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(progressFetches).toBe(1);

    // Cached but currently unobserved (the dashboard while the quiz is open,
    // the learn list while the reader is open): no refetch should be
    // attempted, but every entry must be marked so the next mount re-reads
    // it — the "learnProgress" prefix is what covers both learnProgressAll
    // and learnProgressOne with one entry in the helper.
    client.setQueryData(["dashboard"], { attempts_graded: 3 });
    client.setQueryData(["learnProgressAll", 6], []);

    invalidateStudyCaches(client);

    await waitFor(() => expect(progressFetches).toBe(2));
    expect(client.getQueryState(["dashboard"])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["learnProgressAll", 6])?.isInvalidated).toBe(true);
  });
});
