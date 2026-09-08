import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import AITutorPage from '../pages/student/AITutorPage'
import { t } from '../i18n'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}))

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}))

vi.mock('../api', () => apiMock)
vi.mock('../AuthContext', () => authMock)

const me = { user_id: 1, email: 's@x.com', role: 'student', profile_id: 7, name: 'S', class_level: 6 }

const CONVS = [{ id: 5, title: 'My-Old-Title', created_at: '2026-01-01T00:00:00Z', message_count: 2 }]

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AITutorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('S1.8 history UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() })
    apiMock.get.mockImplementation((path: string) => {
      if (path.startsWith('/tutor/messages/search')) return Promise.resolve([])
      return Promise.resolve([...CONVS])
    })
    apiMock.get.mockResolvedValueOnce([...CONVS]) // initial conversations query
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('rename sends PATCH with the new title', async () => {
    const user = userEvent.setup()
    renderPage()

    const chip = await screen.findByText('My-Old-Title')
    await user.click(chip) // activate the conversation

    await user.click(await screen.findByRole('button', { name: t('rename') }))
    const box = await screen.findByRole('textbox', { name: t('rename') })
    await user.clear(box)
    await user.type(box, 'My-New-Title')
    await user.keyboard('{Enter}')

    await waitFor(() => expect(apiMock.patch).toHaveBeenCalledWith('/tutor/conversations/5', { title: 'My-New-Title' }))
  })

  it('delete sends DELETE and the chip disappears from the list', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    apiMock.get.mockReset()
    let listCalls = 0
    apiMock.get.mockImplementation((path: string) => {
      if (path.startsWith('/tutor/messages/search')) return Promise.resolve([])
      listCalls += 1
      return Promise.resolve(listCalls <= 1 ? [...CONVS] : [])
    })
    renderPage()

    await screen.findByText('My-Old-Title')
    await user.click(await screen.findByRole('button', { name: t('deleteChat') }))

    await waitFor(() => expect(apiMock.del).toHaveBeenCalledWith('/tutor/conversations/5'))
    await waitFor(() => expect(screen.queryByText('My-Old-Title')).toBeNull())
    expect(window.confirm).toHaveBeenCalled()
  })
})
