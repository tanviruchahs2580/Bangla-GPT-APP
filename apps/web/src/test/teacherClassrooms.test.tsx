import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TeacherDashboard from '../pages/TeacherDashboard'
import { t } from '../i18n'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('../api', () => apiMock)

const ROOMS = [
  { id: 1, class_level: 6, section: 'GEN', student_count: 2 },
  { id: 2, class_level: 7, section: 'GEN', student_count: 1 },
]

const ROSTER_ROOM1 = [
  {
    student_id: 11,
    name: 'Rahim',
    class_level: 6,
    email: 'rahim@school.edu',
    invite_pending: true,
    attempts_graded: 2,
    avg_score_pct: 55,
  },
  {
    student_id: 12,
    name: 'Karim',
    class_level: 6,
    email: null,
    invite_pending: false,
    attempts_graded: 0,
    avg_score_pct: null,
  },
]

const EMPTY_ANALYTICS = {
  class_level: 6,
  students: 2,
  chapters: [],
  weak_chapters: [],
  students_detail: [],
}

const IMPORT_RESULT = {
  created: 2,
  failed: 0,
  rows: [
    { name: 'A', email: 'a@school.edu', status: 'created', invite_code: 'abcdef123456' },
    { name: 'B', email: 'b@school.edu', status: 'created', invite_code: 'zyxwvu654321' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.get.mockImplementation((path: string) => {
    if (path === '/teacher/classrooms') return Promise.resolve(structuredClone(ROOMS))
    if (path.endsWith('/roster')) {
      return Promise.resolve(
        path === '/teacher/classrooms/1/roster' ? structuredClone(ROSTER_ROOM1) : [],
      )
    }
    if (path.includes('/analytics')) {
      return Promise.resolve({ ...structuredClone(EMPTY_ANALYTICS), class_level: Number(path.split('/')[3]) })
    }
    return Promise.resolve(null)
  })
  apiMock.post.mockResolvedValue({ id: 3, class_level: 8, section: 'B', student_count: 0 })
})

describe('S2.2 classroom chips + roster + CSV import', () => {
  it('renders classroom chips and switches roster on click', async () => {
    const user = userEvent.setup()
    render(<TeacherDashboard />)

    const chips = await screen.findAllByRole('button', { pressed: true })
    expect(chips.length).toBe(1) // first room selected by default
    await waitFor(() => expect(screen.getByText('Rahim')).toBeInTheDocument())
    expect(screen.getByText('rahim@school.edu')).toBeInTheDocument()
    expect(screen.getByText(new RegExp(t('invitePending')))).toBeInTheDocument()
    // Karim has no email and no pending badge
    expect(screen.getByText('Karim')).toBeInTheDocument()

    const chip7 = await screen.findByRole('button', { name: /7/ })
    await user.click(chip7)
    await waitFor(() =>
      expect(apiMock.get).toHaveBeenCalledWith('/teacher/classrooms/2/roster'),
    )
    await waitFor(() => expect(screen.queryByText('Rahim')).not.toBeInTheDocument())
  })

  it('creates a new classroom with level + section', async () => {
    const user = userEvent.setup()
    render(<TeacherDashboard />)
    await screen.findByText('Rahim')

    const selects = screen.getAllByRole('combobox')
    const levelSelect = selects.find((s) => s.querySelector('option[value="8"]'))
    expect(levelSelect).toBeTruthy()
    await user.selectOptions(levelSelect as HTMLElement, '8')
    await user.clear(screen.getByLabelText(t('section')))
    await user.type(screen.getByLabelText(t('section')), 'B')

    await user.click(screen.getByRole('button', { name: t('newClassroom') }))
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith('/teacher/classrooms', {
        class_level: 8,
        section: 'B',
      }),
    )
    await waitFor(() =>
      expect(screen.getByRole('button', { pressed: true })).toHaveTextContent('8'),
    )
  })

  it('imports a CSV and shows per-row invite codes once', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValue(structuredClone(IMPORT_RESULT))
    render(<TeacherDashboard />)
    await screen.findByText('Rahim')

    await user.type(
      screen.getByPlaceholderText('name,email'),
      'name,email\nA,a@school.edu\nB,b@school.edu',
    )
    await user.click(screen.getByRole('button', { name: t('importBtn') }))

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith('/teacher/classrooms/1/import', {
        csv_text: expect.stringContaining('a@school.edu'),
      }),
    )
    expect(await screen.findByText(t('importCreated', { n: 2 }))).toBeInTheDocument()
    expect(screen.getByText(t('importFailed', { n: 0 }))).toBeInTheDocument()
    expect(screen.getByText('abcdef123456')).toBeInTheDocument()
    expect(screen.getByText('zyxwvu654321')).toBeInTheDocument()
  })
})
