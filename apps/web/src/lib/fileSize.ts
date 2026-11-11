import { t } from "../i18n";

/**
 * A device-storage figure, said in the reader's language.
 *
 * FE-FIX (raw machine copy): the offline library printed `MiB`/`KiB` inside
 * Bangla sentences ("১২.৪ MiB") — the last Latin unit names on a student-facing
 * card. The unit stays binary (`formatBytes` is a storage figure and must not
 * read as network speed), so the fix is the unit NAME, not the maths: the
 * names are i18n keys and the number goes through the same interpolation
 * boundary as every other quantity, which is what gives it Bangla digits.
 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes >= 1_048_576)
    return t("sizeMiB", { n: (bytes / 1_048_576).toFixed(1) });
  if (bytes >= 1024) return t("sizeKiB", { n: Math.round(bytes / 1024) });
  return t("sizeBytes", { n: Math.round(bytes) });
}
