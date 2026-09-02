export interface SourceRef {
  book: string
  chapter: string
  section: string | null
  page: number | null
  score: number
}

export interface AskResponse {
  answer: string
  grounded: boolean
  sources: SourceRef[]
  refused_reason?: string | null
  citation_verified?: boolean | null
}

export interface ConversationOut {
  id: number
  title: string | null
  created_at: string
  message_count: number
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  grounded?: boolean | null
  refused_reason?: string | null
  sources: SourceRef[]
  rating?: number | null
  created_at?: string
}

export interface ChatDoneEvent extends AskResponse {
  user_message_id: number
  message_id: number
}

export interface QuizQuestionPublic {
  id: string
  question_text: string
  options: string[]
}

export interface QuizStarted {
  attempt_id: number
  questions: QuizQuestionPublic[]
  requested: number
  note?: string | null
}

export interface ReviewItem {
  question_text: string
  options: string[]
  chosen: number
  correct_index: number
  is_correct: boolean
  chapter: string
}

export interface QuizResult {
  attempt_id: number
  score_pct: number
  correct: number
  total: number
  review: ReviewItem[]
}

export interface ChapterStat {
  chapter: string
  asked: number
  correct: number
  accuracy: number
}

export interface StudentResponse {
  id: number
  name: string
  class_level: number
}

export interface StudentProgress {
  student: StudentResponse
  attempts_graded: number
  avg_score_pct: number | null
  by_chapter: ChapterStat[]
  weak_chapters: string[]
}

export interface StudentBrief {
  student_id: number
  name: string
  class_level: number
  attempts_graded: number
  avg_score_pct: number | null
}

export interface ClassAnalytics {
  class_level: number
  students: number
  chapters: ChapterStat[]
  weak_chapters: string[]
  students_detail: StudentBrief[]
}

export interface UserPublic {
  id: number
  email: string
  role: string
  created_at: string
}

export interface AdminOverview {
  users_total: number
  students: number
  teachers: number
  admins: number
  parents: number
  quiz_attempts_graded: number
  avg_score_pct: number | null
}

export interface AdminUsersPage {
  total: number
  items: UserPublic[]
}

/* -------- Learn catalog (grounded corpus) -------- */
export interface SubjectOut {
  subject: string
  book: string
  class_levels: number[]
}

export interface ChapterSummaryOut {
  chapter: string
  excerpt: string
  section_count: number
}

export interface SectionOut {
  section: string
  text: string
}

export interface ChapterContentOut {
  subject: string
  class_level: number
  book: string
  chapter: string
  sections: SectionOut[]
}
