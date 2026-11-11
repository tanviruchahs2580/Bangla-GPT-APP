import { tSubject } from "../i18n";

/**
 * The subject picker shared by the tutor, the quiz hub and the create hub.
 *
 * FE-FIX (duplication): this array and its "labels from i18n, evaluated per
 * render" comment existed three times — `AITutorPage`, `StartQuizCard` and
 * `CreateHub` — so a fourth subject had to be added in three places or one
 * picker silently offered a subset. Labels are resolved through `tSubject`
 * (the one mapping the reader, the report and the assigned-work list already
 * use) and therefore per render, so a language switch rewrites them.
 */
export const SUBJECT_VALUES = ["science", "mathematics", "bangla"] as const;

export function subjectOptions(): Array<{ value: string; label: string }> {
  return SUBJECT_VALUES.map((value) => ({
    value,
    label: tSubject(value),
  }));
}
