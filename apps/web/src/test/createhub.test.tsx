/** Wave 2: teacher Create hub — generate, filter, delete flows. */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, it, vi } from 'vitest'
import { CreateHub } from '../components/teacher/CreateHub'
import { t } from '../i18n'
import type { TeacherDocument, TeacherWorkload } from '../api'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
  downloadTeacherDocumentPdf: vi.fn(),
}))

vi.mock('../api', () => ({
  ...apiMock,
  apiBase: '/api',
  getToken: () => 'tok',
}))

const DOC: TeacherDocument = {
  id: 9,
  kind: 'worksheet',
  class_level: 6,
  subject: 'science',
  chapter: 'photosynthesis',
  title: 'Photosynthesis worksheet',
  payload: { questions: [{ question: 'What is photosynthesis?', answer: 'Food making in plants' }] },
  created_at: '2026-09-01T10:00:00',
}

const WORKLOAD: TeacherWorkload = {
  counts: { worksheet: 1, answer_key: 0, homework: 0, rubric: 0, lesson_plan: 0 },
  minutes_saved: { worksheet: 25, answer_key: 0, homework: 0, rubric: 0, lesson_plan: 0 },
  total_minutes_saved: 25,
  estimate: true,
  methodology: 'heuristic',
}

beforeEach(() => {
  apiMock.get.mockImplementation((path: string) => {
    if (path.startsWith('/teacher/documents')) return Promise.resolve([structuredClone(DOC)])
    if (path === '/teacher/jobs') return Promise.resolve([])
    if (path === '/teacher/workload') return Promise.resolve(structuredClone(WORKLOAD))
    return Promise.resolve(null)
  })
  apiMock.post.mockImplementation((path: string) => {
    if (path.startsWith('/teacher/generate/')) return Promise.resolve({ ...structuredClone(DOC), id: 10, sources: [] })
    return Promise.resolve(null)
  })
  apiMock.del.mockResolvedValue(null)
})

it('renders the saved library and the workload estimate', async () => {
  render(<CreateHub />)
  expect(await screen.findByText('Photosynthesis worksheet')).toBeInTheDocument()
  expect(screen.getByText('25')).toBeInTheDocument()
})

it('generates a worksheet synchronously with the chosen class and subject', async () => {
  const user = userEvent.setup()
  render(<CreateHub />)
  await screen.findByText('Photosynthesis worksheet')
  await user.click(screen.getByRole('button', { name: t('genNow') }))
  await waitFor(() =>
    expect(apiMock.post).toHaveBeenCalledWith(
      '/teacher/generate/worksheet',
      expect.objectContaining({ class_level: 6, subject: 'science' }),
    ),
  )
  expect(screen.getAllByText('Photosynthesis worksheet').length).toBeGreaterThanOrEqual(2)
})

it('answer key kind asks for questions; background run queues a job', async () => {
  const user = userEvent.setup()
  render(<CreateHub />)
  await screen.findByText('Photosynthesis worksheet')
  await user.click(screen.getByRole('tab', { name: t('genAnswerKey') }))
  expect(screen.getByText(t('genQuestionsHint'))).toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: t('genQuestionsHint') }), {
    target: { value: 'Q one\nQ two' },
  })
  await user.click(screen.getByRole('button', { name: t('genLater') }))
  await waitFor(() =>
    expect(apiMock.post).toHaveBeenCalledWith(
      '/teacher/jobs',
      expect.objectContaining({ kind: 'answer_key' }),
    ),
  )
})

it('delete removes the row via DELETE /teacher/documents/{id}', async () => {
  const user = userEvent.setup()
  render(<CreateHub />)
  await screen.findByText('Photosynthesis worksheet')
  await user.click(screen.getByRole('button', { name: t('deleteGeneric') }))
  await waitFor(() => expect(apiMock.del).toHaveBeenCalledWith('/teacher/documents/9'))
  expect(screen.queryByText('Photosynthesis worksheet')).not.toBeInTheDocument()
})
