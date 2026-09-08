/** S2.7: weakness heatmap + at-risk support plans render in the teacher UI. */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TeacherDashboard from '../pages/TeacherDashboard'
import { t } from '../i18n'
import type { SupportPlanRow, WeakMatrix } from '../types'

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
    attempts_graded: 2,
    avg_score_pct: 50,
  },
  {
    student_id: 12,
    name: 'Karim',
    class_level: 6,
    email: 'karim@school.edu',
    invite_pending: false,
    attempts_graded: 4,
    avg_score_pct: 25,
  },
]

const MATRIX: WeakMatrix = {
  class_level: 6,
  // backend sorts concepts weakest-first for the class
  concepts: ['beta', 'alpha'],
  students: [
    {
      student_id: 11,
      name: 'Rahim',
      avg_score_pct: 50,
      attempts_graded: 2,
      trend: 'flat',
      at_risk: false,
      cells: {
        alpha: { asked: 4, correct: 4, accuracy: 100, read: true },
        beta: { asked: 4, correct: 0, accuracy: 0, read: false },
      },
    },
    {
      student_id: 12,
      name: 'Karim',
      avg_score_pct: 25,
      attempts_graded: 4,
      trend: 'down',
      at_risk: true,
      cells: {
        alpha: { asked: 2, correct: 1, accuracy: 50, read: false },
        beta: { asked: 2, correct: 0, accuracy: 0, read: true },
      },
    },
  ],
}

const PLAN_ROW: SupportPlanRow = {
  id: 1,
  student_id: 12,
  teacher_id: 1,
  class_level: 6,
  focus_concepts: ['beta', 'alpha'],
  plan: {
    weeks: [
      { week: 1, stage: 'concept', concepts: ['beta', 'alpha'], action: 'read', detail: 'beta, alpha' },
      { week: 2, stage: 'practice', concepts: ['beta', 'alpha'], action: 'quiz', detail: 'beta, alpha' },
      { week: 3, stage: 'assessment', concepts: ['beta', 'alpha'], action: 'test', detail: 'beta, alpha' },
    ],
    focus_concepts: ['beta', 'alpha'],
  },
  created_at: '2026-09-03T00:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.get.mockImplementation((path: string) => {
    if (path === '/teacher/classrooms') return Promise.resolve(structuredClone(ROOMS))
    if (path.endsWith('/roster')) return Promise.resolve(structuredClone(ROSTER))
    if (path === '/teacher/shorttests') return Promise.resolve([])
    if (path === '/teacher/support-plans') return Promise.resolve([])
    if (path.includes('weak-matrix')) return Promise.resolve(structuredClone(MATRIX))
    return Promise.resolve(null)
  })
  apiMock.post.mockImplementation((path: string) => {
    if (path === '/teacher/support-plans') return Promise.resolve(structuredClone(PLAN_ROW))
    return Promise.resolve(null)
  })
})

describe('S2.7 weakness heatmap card', () => {
  it('renders the concept x student grid with token-bucket cells', async () => {
    render(<TeacherDashboard />)
    // names appear in both the roster and the heatmap header
    await screen.findAllByText('Rahim')

    // concept headers and per-student columns present
    expect(screen.getByText('beta')).toBeInTheDocument()
    expect(screen.getByText('alpha')).toBeInTheDocument()
    expect(screen.getAllByText('Karim').length).toBeGreaterThan(1)

    // accuracies render as percentages, weakest cells take the danger bucket
    expect(screen.getAllByText('0%').length).toBe(2)
    expect(screen.getByText('100%')).toBeInTheDocument()
    expect(document.querySelectorAll('td.wm-bad').length).toBe(2)
    expect(document.querySelectorAll('td.wm-mid').length).toBe(1) // Karim x alpha = 50%
    expect(document.querySelectorAll('td.wm-good').length).toBe(1) // Rahim x alpha = 100%

    // read chapters from tutor data surface via the cell title
    expect(screen.getAllByTitle(t('wmRead')).length).toBe(2)

    // avg/trend footer row: downward trend flags Karim, Rahim stays flat.
    // The arrow is its own text node, so match on the cell's combined text.
    const trendCells = (mark: string) =>
      screen
        .queryAllByText((_, el) =>
          Boolean(el?.tagName === 'TD' && (el.textContent ?? '').includes(mark)),
        )
        .filter((el) => el.className.includes('wm-cell'))
    expect(trendCells('▼').length).toBe(1)
    expect(trendCells('▲').length).toBe(0)
    expect(trendCells('–').length).toBe(1)
  })

  it('flags at-risk students and creates a 3-week support plan', async () => {
    const user = userEvent.setup()
    render(<TeacherDashboard />)
    await screen.findAllByText('Rahim')

    // exactly Karim is flagged (avg 25% < 40 OR down trend)
    expect(screen.getAllByText(t('spRisk')).length).toBe(1)
    const btn = screen.getByRole('button', { name: `Karim: ${t('spCreate')}` })
    expect(screen.queryByRole('button', { name: `Rahim: ${t('spCreate')}` })).toBeNull()

    // no plans yet
    expect(screen.getByText(t('spEmpty'))).toBeInTheDocument()

    await user.click(btn)
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith('/teacher/support-plans', { student_id: 12 }),
    )

    // the returned plan renders weeks 1-3 in concept -> practice -> assessment order
    await waitFor(() => expect(screen.queryByText(t('spEmpty'))).toBeNull())
    const weekLine = (n: number, stageKey: string) =>
      screen.getByText((_, el) => {
        const text = el?.textContent ?? ''
        return (
          el?.tagName === 'DIV' &&
          text.startsWith(t('spWeek', { n })) &&
          text.includes(t(stageKey as Parameters<typeof t>[0]))
        )
      })
    weekLine(1, 'spStageConcept')
    weekLine(2, 'spStagePractice')
    weekLine(3, 'spStageAssessment')
    expect(screen.getAllByText(/beta, alpha/).length).toBeGreaterThan(0)
  })

  it('shows the S4.6 weakness rollup chips under each student that has them', async () => {
    const withRollup = structuredClone(MATRIX)
    withRollup.students[1].weak_concepts = ['beta', 'alpha']
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/teacher/classrooms') return Promise.resolve(structuredClone(ROOMS))
      if (path.endsWith('/roster')) return Promise.resolve(structuredClone(ROSTER))
      if (path === '/teacher/shorttests') return Promise.resolve([])
      if (path === '/teacher/support-plans') return Promise.resolve([])
      if (path.includes('weak-matrix')) return Promise.resolve(withRollup)
      return Promise.resolve(null)
    })
    render(<TeacherDashboard />)
    await screen.findAllByText('Rahim')
    // only Karim carries rollup data in this payload -> exactly one chip row,
    // both weakest concepts in rollup order (querySelectorAll avoids the
    // concept-header text collision)
    expect(document.querySelectorAll('.wm-weak-chips').length).toBe(1)
    const chips = document.querySelectorAll('.wm-weak-chips .badge')
    expect(chips.length).toBe(2)
    expect(chips[0]?.textContent).toBe('beta')
    expect(chips[1]?.textContent).toBe('alpha')
  })

  it('shows the empty hint when the class has no graded data', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/teacher/classrooms') return Promise.resolve(structuredClone(ROOMS))
      if (path.endsWith('/roster')) return Promise.resolve(structuredClone(ROSTER))
      if (path === '/teacher/shorttests') return Promise.resolve([])
      if (path === '/teacher/support-plans') return Promise.resolve([])
      if (path.includes('weak-matrix')) {
        return Promise.resolve({ class_level: 6, concepts: [], students: [] })
      }
      return Promise.resolve(null)
    })
    render(<TeacherDashboard />)
    await waitFor(() => expect(screen.getByText(t('wmEmpty'))).toBeInTheDocument())
  })
})
