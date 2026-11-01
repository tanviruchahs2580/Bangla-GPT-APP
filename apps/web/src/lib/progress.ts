import type { ChapterProgressOut } from "../types";

export type Badge = "done" | "reading" | null;

// badge logic: completed -> "done", any read progress -> "reading", none -> null.
export function chapterBadge(
  prog: Pick<ChapterProgressOut, "completed" | "read_pct"> | undefined,
): Badge {
  if (!prog) return null;
  if (prog.completed) return "done";
  if (prog.read_pct > 0) return "reading";
  return null;
}

// TTS is feature-guarded: only offer the button when the browser exposes it.
export function ttsSupported(
  win: Pick<Window, "speechSynthesis"> | undefined = typeof window !==
  "undefined"
    ? window
    : undefined,
): boolean {
  return !!win && "speechSynthesis" in win;
}

/**
 * F-108: read-aloud is only honest when a Bengali voice is installed.
 * Desktop Chrome and Safari commonly expose `speechSynthesis` with an
 * English-only voice list; the Bangla text then gets spoken in an English
 * voice, which a student hears as gibberish.
 */
export function hasBanglaTtsVoice(
  voices: readonly { lang: string }[],
): boolean {
  return voices.some((voice) => voice.lang.toLowerCase().startsWith("bn"));
}
