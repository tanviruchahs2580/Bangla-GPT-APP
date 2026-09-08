// S1.4 — parser for the sectioned tutor answer layout (SYSTEM_PROMPT rule ৬).
// Labels mirror apps/api/src/bangla_gpt_api/services/answer_structure.py exactly.
export const SECTION = {
  simple: 'সহজ ব্যাখ্যা:',
  example: 'উদাহরণ:',
  points: 'মূল বিষয়:',
  check: 'তুমি বুঝেছ?',
} as const

export interface StructuredAnswer {
  structured: boolean
  simple: string
  example: string
  points: string[]
  check: string
  /** Text before the first recognized section (e.g. provider prefix noise). */
  preamble: string
}

const BULLET_RE = /^[-•·]\s*/

/**
 * Split a tutor answer into simple/example/points/check sections.
 * Answers without the layout (refusals, out-of-corpus copies) come back
 * `structured: false` so callers render them as plain text.
 */
export function parseStructuredAnswer(answer: string): StructuredAnswer {
  const empty: StructuredAnswer = {
    structured: false,
    simple: '',
    example: '',
    points: [],
    check: '',
    preamble: '',
  }
  const marks = [
    { key: 'simple' as const, at: answer.indexOf(SECTION.simple) },
    { key: 'example' as const, at: answer.indexOf(SECTION.example) },
    { key: 'points' as const, at: answer.indexOf(SECTION.points) },
    { key: 'check' as const, at: answer.indexOf(SECTION.check) },
  ].filter((m) => m.at >= 0)
  if (marks.length < 3) return empty
  marks.sort((a, b) => a.at - b.at)
  const parts: Record<string, string> = {}
  marks.forEach((m, i) => {
    const start = m.at + SECTION[m.key].length
    const end = i + 1 < marks.length ? marks[i + 1].at : answer.length
    parts[m.key] = answer.slice(start, end).trim()
  })
  const points = (parts.points ?? '')
    .split('\n')
    .map((l) => l.replace(BULLET_RE, '').trim())
    .filter(Boolean)
  return {
    structured: true,
    simple: parts.simple ?? '',
    example: parts.example ?? '',
    points,
    check: parts.check ?? '',
    preamble: answer.slice(0, marks[0].at).trim(),
  }
}
