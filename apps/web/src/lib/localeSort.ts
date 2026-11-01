import { localeTag, type Lang } from "../i18n";

/**
 * F-116: user-visible name/section sorts collate in the app language.
 *
 * A bare `localeCompare` follows the *device* locale: two users looking at
 * the same classrooms, one on an en-US machine and one on a bn-BD machine,
 * could see different orderings of the same Bangla labels, and the ordering
 * was the device's accident rather than the product's choice.
 */
export function localizedCollator(lang?: Lang): Intl.Collator {
  return new Intl.Collator(localeTag(lang));
}

/** Classrooms in level order, then by section under the app-language
 *  collation. Lives here rather than in the pages so Home, Classes and
 *  Assessments order the same shared cache the same way (audit H-04). */
export function byClassLevelThenSection<
  T extends { class_level: number; section: string },
>(rows: readonly T[]): T[] {
  const collator = localizedCollator();
  return [...rows].sort(
    (a, b) =>
      a.class_level - b.class_level || collator.compare(a.section, b.section),
  );
}
