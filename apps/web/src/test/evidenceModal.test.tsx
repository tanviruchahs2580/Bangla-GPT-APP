import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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

// ASCII fixture fields keep the assertions byte-safe (no Bengali literals in this file).
const SOURCE = {
  book: 'Biggan',
  chapter: 'Kosh-Excerpt-Chapter',
  section: 'Cell-Ki',
  page: 12,
  score: 4.2,
  excerpt: 'Koash hosse jibdeher ekok. Sanitized excerpt line two.',
}

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

async function askOneQuestion(user: ReturnType<typeof userEvent.setup>) {
  // S1.8 added a history-search textbox — target the chat input by name.
  const box = await screen.findByRole('textbox', { name: t('askPlaceholder') })
  await user.type(box, 'k')
  await user.keyboard('{Enter}')
  await waitFor(() => expect(apiMock.postStream).toHaveBeenCalled())
}

function sourceChip(): HTMLElement {
  const chip = screen.getAllByRole('button').find((b) => b.className.includes('source-chip'))
  if (!chip) throw new Error('source chip button not found')
  return chip
}

describe('S1.6 evidence modal', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() })
    apiMock.get.mockResolvedValue([])
    apiMock.post.mockResolvedValue({
      id: 1,
      title: null,
      created_at: '2026-01-01T00:00:00Z',
      message_count: 0,
      last_strategy: null,
    })
    apiMock.postStream.mockImplementation(
      async (_url: string, _body: unknown, onToken: (tok: string) => void) => {
        onToken('Koash hosse ekok.')
        return {
          message_id: 2,
          user_message_id: 1,
          answer: 'Koash hosse ekok.',
          grounded: true,
          sources: [SOURCE],
        }
      },
    )
  })

  it('source chip opens the evidence modal with the sanitized excerpt and path', async () => {
    const user = userEvent.setup()
    renderPage()
    await askOneQuestion(user)

    // The chip advertises the evidence action through its accessible name.
    const chip = await waitFor(sourceChip)
    expect(chip.getAttribute('aria-label')).toContain(t('evidenceTitle'))
    await user.click(chip)

    const dialog = await screen.findByRole('dialog')
    // Full sanitized excerpt shown, not just the short citation label.
    expect(within(dialog).getByText(SOURCE.excerpt)).toBeInTheDocument()
    // Book / chapter / section breadcrumb path.
    expect(dialog.textContent).toContain('Biggan')
    expect(dialog.textContent).toContain('Cell-Ki')
    // Raw provider markup never reaches the UI.
    expect(dialog.textContent).not.toContain('<evidence>')
    expect(dialog.textContent).not.toContain('</evidence>')
    expect(dialog.textContent).not.toContain('<user_question>')
  })

  it('closes the modal via the close button', async () => {
    const user = userEvent.setup()
    renderPage()
    await askOneQuestion(user)
    await user.click(await waitFor(sourceChip))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: t('close') }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})
