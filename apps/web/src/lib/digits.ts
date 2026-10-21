/**
 * Numeral policy (AUD-G-11 / G-22).
 *
 * Display follows the UI language: Bangla screens show Bengali digits and
 * Bangla-style grouping through `Intl` with the `bn-BD` locale, English
 * screens show ASCII digits. Input accepts BOTH scripts everywhere a number is
 * expected, because a Bangla keyboard produces ০-৯ and a browser's
 * `type="number"` field silently discards those keystrokes — the teacher then
 * believes the field is broken. Values are normalised to ASCII before they are
 * parsed or sent, so the API only ever sees one numeral system.
 *
 * Currency: the app shows no prices today; if one is ever displayed it must use
 * the taka sign `৳` with `Intl.NumberFormat("bn-BD", { style: "currency",
 * currency: "BDT" })` (or the English equivalent) rather than a bare number, so
 * the policy is stated here rather than invented per screen.
 */
import { getLang } from "../i18n";

const BENGALI_ZERO = 0x09e6; // ০
const ASCII_ZERO = 0x30;

/** `"১২৩"` -> `"123"`. Other characters are left untouched. */
export function toAsciiDigits(value: string): string {
  let out = "";
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    out +=
      code >= BENGALI_ZERO && code <= BENGALI_ZERO + 9
        ? String.fromCharCode(ASCII_ZERO + (code - BENGALI_ZERO))
        : ch;
  }
  return out;
}

/** `"123"` -> `"১২৩"`. Used for display when the UI language is Bangla. */
export function toBengaliDigits(value: string): string {
  let out = "";
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    out +=
      code >= ASCII_ZERO && code <= ASCII_ZERO + 9
        ? String.fromCharCode(BENGALI_ZERO + (code - ASCII_ZERO))
        : ch;
  }
  return out;
}

/** Parse a user-typed number that may be written in either script. */
export function parseDigits(raw: string, fallback = Number.NaN): number {
  const ascii = toAsciiDigits(raw).trim();
  if (ascii === "") return fallback;
  const n = Number(ascii);
  return Number.isFinite(n) ? n : fallback;
}

/** The locale Intl uses for the current UI language. */
export function localeFor(lang: string = getLang()): string {
  return lang === "bn" ? "bn-BD" : "en-US";
}

/** Language-aware number formatting; the digits follow the UI language. */
export function formatNumber(
  value: number,
  options?: Intl.NumberFormatOptions,
): string {
  if (!Number.isFinite(value)) return "";
  try {
    return new Intl.NumberFormat(localeFor(), options).format(value);
  } catch {
    return String(value);
  }
}
