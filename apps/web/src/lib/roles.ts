/**
 * Machine role -> localized label.
 *
 * Roles arrive from the API as English enums (`student`, `school_admin`).
 * Rendering them raw put English words inside an otherwise Bengali admin table,
 * and the same six-line map had been copied into MePage and TeacherProfilePage.
 *
 * This lives outside `i18n.ts` on purpose: that file is the two dictionaries
 * plus `t`, and `scripts/check_i18n.py` reads it as such. A second object
 * literal in there is indistinguishable from translations to that parser.
 */

import { t } from "../i18n";

export const ROLE_LABEL: Record<string, Parameters<typeof t>[0]> = {
  student: "roleStudent",
  teacher: "roleTeacher",
  parent: "roleParent",
  admin: "roleAdmin",
  school_admin: "roleSchoolAdmin",
};

/** Localized role name; an unknown role falls back to its raw value. */
export function roleLabel(role: string): string {
  const key = ROLE_LABEL[role];
  return key ? t(key) : role;
}
