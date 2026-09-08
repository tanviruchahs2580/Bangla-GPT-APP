import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import QuizPage from '../pages/student/QuizPage'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}))

vi.mock('../api', () => apiMock)
vi.mock('../AuthContext', () => authMock)

const me = { user_id: 1, email: 's@x.com', role: 'student', profile_id: 7, name: 'S', class_level: 6 }

function renderQuiz() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <QuizPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('QuizPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() })
    apiMock.get.mockResolvedValue({ attempts_graded: 0, avg_score_pct: null })
  })

  it('posts the user-selected subject, not the hardcoded default', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValue({
      attempt_id: 1,
      questions: [{ id: 1, text: 'q', options: ['a', 'b', 'c', 'd'] }],
    })
    renderQuiz()

    const subjectSelects = screen.getAllByRole('combobox')
    // first combobox is question count, second is subject
    await user.selectOptions(subjectSelects[1], 'mathematics')

    await user.click(screen.getAllByRole('button', { name: /কুইজ শুরু/ })[0])

    expect(apiMock.post).toHaveBeenCalledWith('/quizzes', expect.objectContaining({ subject: 'mathematics' }))
  })
})
