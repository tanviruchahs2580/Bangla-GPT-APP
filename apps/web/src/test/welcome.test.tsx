/** Blueprint screens 01-02: welcome renders both CTAs and tracks the tap. */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import WelcomePage from '../pages/WelcomePage'
import { t } from '../i18n'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(() => Promise.resolve({})),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  apiBase: '/api',
}))

vi.mock('../api', () => apiMock)

describe('WelcomePage', () => {
  it('renders the tagline and both calls to action', () => {
    render(
      <MemoryRouter>
        <WelcomePage />
      </MemoryRouter>,
    )
    expect(screen.getByText(t('welcomeTagline'))).toBeInTheDocument()
    const start = screen.getByRole('link', { name: t('welcomeStart') })
    const login = screen.getByRole('link', { name: t('welcomeLogin') })
    expect(start).toHaveAttribute('href', '/register')
    expect(login).toHaveAttribute('href', '/login')
  })

  it('tracks the CTA tap without blocking navigation', () => {
    render(
      <MemoryRouter>
        <WelcomePage />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('link', { name: t('welcomeStart') }))
    expect(apiMock.post).toHaveBeenCalledWith('/events', {
      name: 'welcome_cta',
      props: { cta: 'register' },
    })
  })
})
