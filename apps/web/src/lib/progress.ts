import type { ChapterProgressOut } from '../types'

export type Badge = 'done' | 'reading' | null

// S1.2 badge logic: completed → ✓, any read progress → ○, none → no badge.
export function chapterBadge(prog: Pick<ChapterProgressOut, 'completed' | 'read_pct'> | undefined): Badge {
  if (!prog) return null
  if (prog.completed) return 'done'
  if (prog.read_pct > 0) return 'reading'
  return null
}

// S1.2 TTS is feature-guarded: only offer the button when the browser exposes it.
export function ttsSupported(win: Pick<Window, 'speechSynthesis'> | undefined = typeof window !== 'undefined' ? window : undefined): boolean {
  return !!win && 'speechSynthesis' in win
}
