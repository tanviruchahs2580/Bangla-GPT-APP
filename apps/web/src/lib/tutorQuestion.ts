import { t } from "../i18n";

/**
 * The tutor question bound, in one place.
 *
 * FE-FIX-016: `ChatSendRequest.message` is `Field(min_length=3,
 * max_length=1000)` (apps/api .../schemas.py:235), and nothing checked it
 * client-side — a Banglish question like `"ki"` left the composer, came back
 * 422, and was reported with the generic "কিছু একটা সমস্যা হয়েছে", which names
 * neither the field nor the rule. `ChapterAsk` had always done this check; it
 * is shared now so the tutor cannot drift from the API's bound or from it.
 */
export const MIN_QUESTION_CHARS = 3;
export const MAX_QUESTION_CHARS = 1000;

/** Copy for a question outside the bound, or null when it may be sent. */
export function questionLengthError(text: string): string | null {
  const value = text.trim();
  if (value.length < MIN_QUESTION_CHARS) return t("questionTooShort");
  if (value.length > MAX_QUESTION_CHARS) return t("questionTooLong");
  return null;
}
