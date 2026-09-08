/** S4.8: admin refusal audit card renders aggregate counts, never content. */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import AdminDashboard from '../pages/AdminDashboard'
import { t } from '../i18n'
import type { RefusalAudit } from '../types'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  // S5.10: AdminDashboard now loads the feedback triage queue on mount.
  getFeedbackQueue: vi.fn(() =>
    Promise.resolve({ rows: [], total: 0, open_count: 0, limit: 20, offset: 0 }),
  ),
  triageFeedback: vi.fn(),
  startImpersonation: vi.fn(),
}))

vi.mock('../api', () => ({
  ...apiMock,
  apiBase: '/api',
  getToken: () => 'tok',
}))

const AUDIT: RefusalAudit = {
  days: 30,
  total_refusals: 7,
  by_reason: { self_harm: 2, sexual_content: 5 },
  by_class: { '6': 4, '9': 3 },
  last_refusal_at: '2026-09-05T10:00:00',
}

beforeEach(() => {
  apiMock.get.mockReset().mockImplementation((url: string) => {
    if (url.startsWith('/admin/safety/refusals')) return Promise.resolve(AUDIT)
    if (url.startsWith('/admin/users')) {
      return Promise.resolve({ total: 0, items: [] })
    }
    if (url.startsWith('/admin/analytics/overview')) {
      return Promise.resolve({
        users_total: 0,
        students: 0,
        teachers: 0,
        admins: 1,
        parents: 0,
        quiz_attempts_graded: 0,
        avg_score_pct: null,
      })
    }
    return Promise.resolve([])
  })
  apiMock.post.mockReset().mockResolvedValue({})
  apiMock.patch.mockReset().mockResolvedValue({})
  apiMock.del.mockReset().mockResolvedValue({})
})

it('shows refusal totals, reasons and classes from the audit endpoint', async () => {
  render(<AdminDashboard />)
  await waitFor(() => expect(screen.getByText(t('admSafety'))).toBeTruthy())
  await waitFor(() => expect(screen.getByText('7')).toBeTruthy())
  expect(screen.getByText('self_harm')).toBeTruthy()
  expect(screen.getByText('sexual_content')).toBeTruthy()
  expect(screen.getByText(`${t('admRefusalClass')} 6: 4`)).toBeTruthy()
  expect(screen.getByText(`${t('admRefusalClass')} 9: 3`)).toBeTruthy()
  expect(apiMock.get).toHaveBeenCalledWith('/admin/safety/refusals')
})

it('shows the empty state when nothing was refused', async () => {
  apiMock.get.mockImplementation((url: string) => {
    if (url.startsWith('/admin/safety/refusals')) {
      return Promise.resolve({
        days: 30,
        total_refusals: 0,
        by_reason: {},
        by_class: {},
        last_refusal_at: null,
      })
    }
    if (url.startsWith('/admin/users')) return Promise.resolve({ total: 0, items: [] })
    return Promise.resolve([])
  })
  render(<AdminDashboard />)
  await waitFor(() => expect(screen.getByText(t('admNoRefusals'))).toBeTruthy())
  expect(screen.getByText('0')).toBeTruthy()
})
