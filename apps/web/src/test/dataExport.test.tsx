import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import MePage from '../pages/student/MePage'
import { friendlyError } from '../errors'
import { t } from '../i18n'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  generateInviteCode: vi.fn(),
  apiBase: '/api',
}))

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}))

vi.mock('../api', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api')>()), ...apiMock }))
vi.mock('../AuthContext', () => authMock)

const me = { user_id: 1, email: 's@x.com', role: 'student', profile_id: 7, name: 'S', class_level: 6 }

const EXPORT_PAYLOAD = {
  user: { id: 1, email: 's@x.com', role: 'student' },
  profile: { type: 'student', id: 7 },
  quiz_attempts: [],
  parent_links: [],
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <MePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('data export button (BUG-2 regression)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() })
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/users/me/export') return Promise.resolve(EXPORT_PAYLOAD)
      return Promise.resolve(null)
    })
    // jsdom does not implement blob URLs; stub the object-URL round-trip.
    URL.createObjectURL = vi.fn(() => 'blob:mock-export')
    URL.revokeObjectURL = vi.fn()
  })

  it('fetches the export with the authed API client instead of a plain anchor link', async () => {
    const { container } = renderPage()
    // The old implementation was a bare <a href="/api/users/me/export">, which
    // the browser fetched without the bearer token and got a 401.
    expect(container.querySelector('a[href="/api/users/me/export"]')).toBeNull()

    await userEvent.click(await screen.findByText(t('exportData')))

    expect(apiMock.get).toHaveBeenCalledWith('/users/me/export')
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-export')
  })

  it('surfaces a friendly error when the export call fails', async () => {
    apiMock.get.mockImplementation((path: string) => {
      if (path === '/users/me/export') return Promise.reject({ rawDetail: 'nope' })
      return Promise.resolve(null)
    })
    renderPage()
    await userEvent.click(await screen.findByText(t('exportData')))
    expect(await screen.findByText(friendlyError('nope').text)).toBeInTheDocument()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })
})
