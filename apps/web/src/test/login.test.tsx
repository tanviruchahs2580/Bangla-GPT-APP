import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from '../pages/LoginPage'
import { AuthProvider } from '../AuthContext'

const apiMock = vi.hoisted(() => ({
  login: vi.fn(),
  fetchMe: vi.fn(),
  logout: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
}))

vi.mock('../api', () => apiMock)

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

function renderLogin() {
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('LoginPage (B8 UX contract)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.fetchMe.mockResolvedValue(null)
    apiMock.logout.mockReturnValue(undefined)
    apiMock.setUnauthorizedHandler.mockImplementation(() => () => undefined)
    localStorage.clear()
  })

  it('renders localized form with autocomplete attributes', () => {
    renderLogin()
    const email = screen.getByLabelText(/ইমেইল|Email/i)
    expect(email).toHaveAttribute('autocomplete', 'email')
    expect(screen.getByRole('button', { name: /লগইন|Log in/i })).toBeInTheDocument()
  })

  it('surfaces the machine code as friendly copy on failure', async () => {
    apiMock.login.mockRejectedValue(
      Object.assign(new Error('Email verification required'), {
        code: 'email_unverified',
      }),
    )
    const { userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()
    renderLogin()
    await user.type(screen.getByLabelText('ইমেইল'), 'a@b.com')
    await user.type(screen.getByLabelText(/পাসওয়ার্ড/), 'longpassword1')
    await user.click(screen.getByRole('button', { name: /লগইন|Log in/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('যাচাই')
    expect(apiMock.login).toHaveBeenCalledOnce()
  })
})
