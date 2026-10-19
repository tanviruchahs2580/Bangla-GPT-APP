/**
 * Parsing the API's timestamps.
 *
 * The backend keeps every stored datetime naive and in UTC — it writes
 * `datetime.now(UTC).replace(tzinfo=None)` — and pydantic serialises that as
 * `"2026-10-20T04:30:00"` with no offset. `new Date("2026-10-20T04:30:00")`
 * reads an offset-less string as **local** time, so handing one straight to
 * `toLocaleString()` showed every user outside UTC a time that was wrong by
 * their whole offset — six hours early in Dhaka, on assignment and quiz
 * deadlines, the admin refusal panel and the status page.
 *
 * `parseServerDate` restores the missing offset. A value that already carries
 * one (anything ending in Z or ±hh:mm) is passed through untouched, so this
 * stays correct if the API ever starts sending aware timestamps.
 */

import { localeFor } from "./digits";

const OFFSETLESS_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

export function parseServerDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(
    OFFSETLESS_DATETIME.test(value) ? `${value}Z` : value,
  );
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** `toLocaleString` for an API timestamp, with the UTC offset restored.
 *
 * AUD-G-15: the locale is the app's, not the browser's. `undefined` meant a
 * Bangla screen showed 18/10/2026 while the rest of the page was in Bangla —
 * `bn-BD` renders the same instant as ১৮/১০/২০২৬, matching the numeral policy
 * in `lib/digits.ts`. */
export function formatServerDateTime(value: string | null | undefined): string {
  return parseServerDate(value)?.toLocaleString(localeFor()) ?? "";
}

/** `toLocaleDateString` for an API timestamp, with the UTC offset restored. */
export function formatServerDate(
  value: string | null | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  return parseServerDate(value)?.toLocaleDateString(localeFor(), options) ?? "";
}
