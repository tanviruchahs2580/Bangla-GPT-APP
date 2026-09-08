import { readFileSync } from 'node:fs'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TeacherDashboard from '../pages/TeacherDashboard'
import { t } from '../i18n'
import type { LessonPlan } from '../types'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('../api', () => ({
  ...apiMock,
  apiBase: '/api',
  getToken: () => 'tok',
}))

const ROOMS = [{ id: 1, class_level: 6, section: 'GEN', student_count: 2 }]
const ROSTER = [
  {
    student_id: 11,
    name: 'Rahim',
    class_level: 6,
    email: 'rahim@school.edu',
    invite_pending: false,
    attempts_graded: 1,
    avg_score_pct: 60,
  },
]
const EMPTY_ANALYTICS = {
  class_level: 6,
  students: 1,
  chapters: [],
  weak_chapters: [],
  students_detail: [],
}

const PLAN: LessonPlan = {
  sections: {
    objective: 'obj-text',
    previous_knowledge: 'prev-text',
    introduction: 'intro-text',
    main_explanation: 'main-text',
    activity: 'act-text',
    questions: 'q-text',
    assessment: 'assess-text',
    homework: 'hw-text',
  },
  sources: [],
  class_level: 6,
  subject: 'science',
  chapter: 'kosh',
  minutes: 35,
  level: 'average',
}

const SECTION_LABEL_KEYS = [
  'lpSecObjective',
  'lpSecPrevious',
  'lpSecIntro',
  'lpSecMain',
  'lpSecActivity',
  'lpSecQuestions',
  'lpSecAssessment',
  'lpSecHomework',
] as const

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.get.mockImplementation((path: string) => {
    if (path === '/teacher/classrooms') return Promise.resolve(structuredClone(ROOMS))
    if (path.endsWith('/roster')) return Promise.resolve(structuredClone(ROSTER))
    if (path === '/teacher/shorttests') return Promise.resolve([])
    if (path.includes('/analytics')) return Promise.resolve(structuredClone(EMPTY_ANALYTICS))
    return Promise.resolve(null)
  })
  apiMock.post.mockImplementation((path: string) => {
    if (path === '/teacher/lesson-plans') return Promise.resolve(structuredClone(PLAN))
    return Promise.resolve(null)
  })
})

describe('S2.6 lesson plan copilot card', () => {
  it('generates eight editable sections and offers printing', async () => {
    const user = userEvent.setup()
    render(<TeacherDashboard />)
    await screen.findByText('Rahim')

    const genBtn = screen.getByRole('button', { name: t('lpGenerate') })
    expect(genBtn).toBeDisabled() // no chapter typed yet

    await user.type(screen.getByLabelText(t('lpChapterLabel')), 'kosh')
    expect(genBtn).toBeEnabled()
    await user.click(genBtn)

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith('/teacher/lesson-plans', {
        class_level: 6,
        subject: 'science',
        chapter: 'kosh',
        minutes: 35,
        level: 'average',
      }),
    )

    // all eight sections render, in spec order, each editable
    const labels = SECTION_LABEL_KEYS.map((k) => t(k))
    for (const label of labels) {
      expect(screen.getByLabelText(label)).toBeInTheDocument()
    }
    expect(screen.getByDisplayValue('obj-text')).toBeInTheDocument()
    expect(screen.getByDisplayValue('hw-text')).toBeInTheDocument()

    // editing one section does not trigger another AI call
    await user.type(screen.getByLabelText(t('lpSecObjective')), ' more')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    expect(screen.getByDisplayValue('obj-text more')).toBeInTheDocument()

    // print control present; print CSS ships in the stylesheet
    expect(screen.getByRole('button', { name: t('lpPrint') })).toBeInTheDocument()
  })
})

describe('S2.6 print stylesheet', () => {
  it('contains a clean lesson-plan print rule block', () => {
    const src = readFileSync('src/styles.css', 'utf-8') // vitest cwd = apps/web
    expect(src).toMatch(/@media print\s*\{/)
    expect(src).toMatch(/\.lesson-print\s*,\s*\.lesson-print\s*\*\s*\{[^}]*visibility:\s*visible/)
    expect(src).toMatch(/\.lesson-print\s*\{[^}]*position:\s*absolute/)
    // the print button itself never reaches the page
    expect(src).toMatch(/\.lp-no-print\s*\{[^}]*display:\s*none/)
  })
})
