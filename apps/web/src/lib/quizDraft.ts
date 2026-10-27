/**
 * B-03: the in-flight quiz draft, shared by the quiz page (write/restore)
 * and the logout scrub (privacy) without either importing the other.
 *
 * A PWA update, battery-saver kill or accidental reload used to wipe an
 * in-progress quiz outright — a rural student on 2G lost the attempt AND
 * every answer, with the teacher-assigned work still sitting open. The
 * draft is sessionStorage: it survives the reload, dies with the tab, and
 * leaves nothing on a shared school device after logout (api.ts scrubs the
 * key on sign-out alongside the F-036 wipe).
 */
import type { QuizStarted } from "../types";

export const QUIZ_DRAFT_KEY = "bgpt_quiz_draft";

export interface QuizDraft {
  started: QuizStarted;
  answers: Record<number, number>;
  current: number;
}

export function readQuizDraft(): QuizDraft | null {
  try {
    const raw = sessionStorage.getItem(QUIZ_DRAFT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    const d = parsed as QuizDraft;
    if (
      !d ||
      typeof d !== "object" ||
      typeof d.started?.attempt_id !== "number" ||
      !Array.isArray(d.started?.questions) ||
      d.started.questions.length === 0 ||
      typeof d.answers !== "object" ||
      typeof d.current !== "number"
    )
      return null;
    return d;
  } catch {
    /* storage unavailable or unparsable: start clean */
    return null;
  }
}

export function clearQuizDraft(): void {
  try {
    sessionStorage.removeItem(QUIZ_DRAFT_KEY);
  } catch {
    /* storage unavailable */
  }
}
