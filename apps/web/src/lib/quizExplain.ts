// S1.7 — Quiz explain loop: structured context payload handed from a wrong
// quiz answer to the AI tutor, plus the message builder. Pure module.
import type { ReviewItem } from '../types'

/** sessionStorage key holding the last graded result for the explain back-link. */
export const LAST_RESULT_KEY = 'bangla-gpt:last-quiz-result'

export interface QuizExplainPayload {
  question: string
  options: string[]
  correct_index: number
  user_answer: number
  chapter: string
}

/** Map a graded review item to the explain context payload. */
export function buildExplainPayload(item: ReviewItem): QuizExplainPayload {
  return {
    question: item.question_text,
    options: item.options,
    correct_index: item.correct_index,
    user_answer: item.chosen,
    chapter: item.chapter,
  }
}

const LETTERS = ['ক', 'খ', 'গ', 'ঘ', 'ঙ', 'চ']

function optionLabel(p: QuizExplainPayload, idx: number): string {
  const letter = LETTERS[idx] ?? String(idx + 1)
  return `${letter}) ${p.options[idx] ?? ''}`.trim()
}

/** Compose the tutor question that carries the full quiz context. */
export function explainMessage(p: QuizExplainPayload): string {
  const lines: string[] = []
  lines.push('আমি কুইজে এই প্রশ্নে ভুল করেছি। ব্যাখ্যা করে বুঝিয়ে দাও।')
  lines.push(`অধ্যায়: ${p.chapter}`)
  lines.push(`প্রশ্ন: ${p.question}`)
  p.options.forEach((_, i) => lines.push(`  ${optionLabel(p, i)}`))
  lines.push(`আমার উত্তর: ${p.user_answer >= 0 ? optionLabel(p, p.user_answer) : '(কোনো উত্তর দেইনি)'}`)
  lines.push(`সঠিক উত্তর: ${optionLabel(p, p.correct_index)}`)
  lines.push('বুঝিয়ে বলো কেন সঠিক উত্তরটা ঠিক, আর আমার উত্তরটা কেন ভুল ছিল।')
  return lines.join('\n')
}
