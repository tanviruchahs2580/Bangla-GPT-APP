/**
 * Shared cache invalidation for study actions.
 *
 * react-query is configured with `staleTime: 30_000` and
 * `refetchOnWindowFocus: false`, so a mutation that does not invalidate its
 * read keys leaves every mounted screen confidently stale. The concrete
 * defects this closes (found in audit, both reproducible):
 *
 * - finishing a quiz showed the PRE-quiz average and streak on the practice
 *   hub — the result screen's only exit navigates back into it — and a Home
 *   visit inside the stale window showed the old numbers there too;
 * - a chapter read to 100% kept its "reading" badge and the subject ring
 *   stayed unchanged, because `upsertLearnProgress` invalidated nothing.
 *
 * Key matching is PREFIX-wise on whole elements, not string prefixes:
 * ["progress"] matches ["progress", profileId], but ["learnProgress"]
 * matches nothing — the two learn keys are `learnProgressAll` and
 * `learnProgressOne`, and both are listed explicitly below. (The
 * invalidation test caught that exact mistake before it shipped.)
 */

import type { QueryClient } from "@tanstack/react-query";

/** Query keys (or element-wise prefixes) every study mutation can stale. */
const STUDY_KEYS = [
  "progress",
  "dashboard",
  "activity",
  "revision-due",
  "learnProgressAll",
  "learnProgressOne",
  // FE-05: the "assigned by teacher" hub (short tests + bulk assignments)
  // keeps its own keys, and the teacher-assigned tab's badge and Start
  // buttons read them. Submitting from inside that tab used to leave the
  // finished work sitting there as open for the whole staleTime window —
  // the student's honest "did it go through?" moment answered with a lie.
  "shorttests-mine",
  "assignments-mine",
] as const;

export function invalidateStudyCaches(queryClient: QueryClient): void {
  for (const key of STUDY_KEYS) {
    void queryClient.invalidateQueries({ queryKey: [key] });
  }
}
