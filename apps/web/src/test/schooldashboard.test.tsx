import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SchoolDashboard from '../pages/SchoolDashboard'
import { t } from '../i18n'
import type { SchoolHealth } from '../types'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('../api', () => ({
  ...apiMock,
  apiBase: '/api',
  getToken: () => 'tok',
}))

const HEALTH: SchoolHealth = {
  school_id: 3,
  name: 'Anondo High School',
  code: 'CFPLFN93',
  students: 6,
  teachers: 2,
  classrooms: 2,
  sessions_7d: 11,
  strong: 2,
  support: 1,
  risk: 2,
  ungraded: 1,
  strong_pct: 40,
  support_pct: 20,
  risk_pct: 40,
  at_risk: [
    {
      student_id: 11,
      name: 'Rahim',
      class_level: 6,
      section: 'GEN',
      attempts_graded: 2,
      avg_score_pct: 20,
      trend: 'down',
    },
    {
      student_id: 12,
      name: 'Karim',
      class_level: 7,
      section: 'GREEN',
      attempts_graded: 1,
      avg_score_pct: 30,
      trend: 'flat',
    },
  ],
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SchoolDashboard />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.get.mockResolvedValue(structuredClone(HEALTH))
})

describe('S3.2 school dashboard', () => {
  it('renders counts, health percentages and the cross-class at-risk list', async () => {
    renderPage()
    await screen.findByText('Anondo High School')
    expect(apiMock.get).toHaveBeenCalledWith('/school/overview')
    expect(screen.getByText(t('schoolDashboard'))).toBeInTheDocument()
    expect(screen.getByText(new RegExp('CFPLFN93'))).toBeInTheDocument()
    // stat tiles
    expect(screen.getByText('11')).toBeInTheDocument()
    // health buckets (40% = strong+risk stats; 20% = support stat and Rahim's badge)
    expect(screen.getAllByText('40%')).toHaveLength(2)
    expect(screen.getAllByText('20%')).toHaveLength(2)
    // at-risk rows from both classes
    expect(screen.getByText('Rahim')).toBeInTheDocument()
    expect(screen.getByText('Karim')).toBeInTheDocument()
    expect(screen.getByText('6 · GEN')).toBeInTheDocument()
    expect(screen.getByText('7 · GREEN')).toBeInTheDocument()
    expect(screen.getByText('down')).toBeInTheDocument()
  })

  it('shows the empty at-risk message when nobody is flagged', async () => {
    apiMock.get.mockResolvedValue({ ...structuredClone(HEALTH), at_risk: [] })
    renderPage()
    await screen.findByText('Anondo High School')
    expect(screen.getByText(t('sdEmpty'))).toBeInTheDocument()
    expect(screen.queryByText('Rahim')).not.toBeInTheDocument()
  })
})
