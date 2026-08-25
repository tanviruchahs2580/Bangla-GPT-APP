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
}

export interface QuizQuestionPublic {
  id: string
  question_text: string
  options: string[]
}

export interface QuizStarted {
  attempt_id: number
  questions: QuizQuestionPublic[]
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
