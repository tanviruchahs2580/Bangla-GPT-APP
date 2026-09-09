// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { NotificationBell } from '../components/NotificationBell'
import { setLang } from '../i18n'
import type { NotificationList } from '../api'

const apiMock = vi.hoisted(() => ({
  getNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
}))

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  ...apiMock,
}))

const LIST: NotificationList = {
  items: [
    {
      id: 2,
      kind: 'parent_link',
      // Backend wire codes are snake_case; dict keys are camelCase.
      code: 'notif_parent_linked',
      params: { student_id: 124 },
      link: '/student/me',
      read_at: null,
      created_at: '2026-09-08T15:52:00',
    },
    {
      id: 3,
      kind: 'assignment',
      code: 'notif_quiz_assigned',
      params: { subject: 'Physics', chapter: 'Motion', count: 5 },
      link: '/student/quiz',
      read_at: null,
      created_at: '2026-09-08T15:53:00',
    },
    {
      id: 4,
      kind: 'mystery',
      code: 'notif_never_seen_before',
      params: { any: 'thing' },
      link: null,
      read_at: '2026-09-08T15:54:00',
      created_at: '2026-09-08T15:54:00',
    },
  ],
  unread_count: 2,
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.setItem('bgpt_lang', 'en')
  setLang('en')
  apiMock.getNotifications.mockResolvedValue(LIST)
  apiMock.markNotificationRead.mockResolvedValue({})
})

describe('NotificationBell code mapping', () => {
  it('renders localized copy for snake_case wire codes and falls back safely', async () => {
    // Regression: the bell crashed the whole app when an unknown wire code
    // hit t() with params (undefined.replaceAll inside the translator).
    render(
      <MemoryRouter>
        <NotificationBell />
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /notifications/i }))
    await waitFor(() => expect(screen.getByText('Guardian link established')).toBeInTheDocument())
    // Params are interpolated into the translated template.
    expect(screen.getByText(/Physics.*Motion/)).toBeInTheDocument()
    // Unknown code: raw wire code shown, no crash.
    expect(screen.getByText('notif_never_seen_before')).toBeInTheDocument()
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })
})
