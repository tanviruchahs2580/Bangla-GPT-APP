/**
 * Parsing and formatting the API's timestamps.
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
 *
 * Formatting is by the *app* language and the product timezone, not by the
 * device (F-116): `toLocaleString()` followed the OS locale, so a bn-UI user
 * on an en-US laptop read "10/20/2026, 10:30:00 AM" in the middle of Bangla
 * screens. The API's instants are Dhaka instants for this product, so the
 * timezone is pinned instead of silently depending on the viewer.
 */

import { getLang, localeTag, type Lang } from "../i18n";

const OFFSETLESS_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;
const TIME_ZONE = "Asia/Dhaka";

export function parseServerDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(
    OFFSETLESS_DATETIME.test(value) ? `${value}Z` : value,
  );
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/** Date+time for an API timestamp, in the app language and Asia/Dhaka. */
export function formatServerDateTime(
  value: string | null | undefined,
  lang: Lang = getLang(),
): string {
  const date = parseServerDate(value);
  if (!date) return "";
  return new Intl.DateTimeFormat(localeTag(lang), {
    timeZone: TIME_ZONE,
  }).format(date);
}

/** Date for an API timestamp, in the app language and Asia/Dhaka. */
export function formatServerDate(
  value: string | null | undefined,
  options?: Intl.DateTimeFormatOptions,
  lang: Lang = getLang(),
): string {
  const date = parseServerDate(value);
  if (!date) return "";
  return new Intl.DateTimeFormat(localeTag(lang), {
    timeZone: TIME_ZONE,
    ...options,
  }).format(date);
}
