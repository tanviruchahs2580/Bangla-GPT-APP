export interface SourceRef {
  book: string;
  chapter: string;
  section: string | null;
  page: number | null;
  score: number;
  /** S1.6: sanitized textbook excerpt for the evidence modal. */
  excerpt?: string | null;
}

export interface AskResponse {
  answer: string;
  grounded: boolean;
  sources: SourceRef[];
  refused_reason?: string | null;
  citation_verified?: boolean | null;
  // Wave 2: numeric grounding confidence 0-1 (null = pre-wave answer)
  confidence?: number | null;
}

export interface ConversationOut {
  id: number;
  title: string | null;
  last_strategy?: string | null;
  created_at: string;
  message_count: number;
}

/** S1.8: one history-search hit. */
export interface MessageSearchHit {
  conversation_id: number;
  conversation_title: string | null;
  message_id: number;
  role: string;
  snippet: string;
  created_at: string;
}

/** S1.9: one heatmap cell (date is ISO, Asia/Dhaka day). */
export interface ActivityDay {
  date: string;
  questions: number;
  quizzes: number;
  minutes: number;
}

/** S1.9: streak + heatmap window for a student. */
export interface ActivitySummary {
  streak: number;
  today: string;
  days: ActivityDay[];
}

/** S1.10: one SM-2-lite revision item. */
export interface RevisionItemOut {
  id: number;
  question: string;
  options: string[];
  correct_index: number;
  chapter: string;
  reps: number;
  interval_days: number;
  ease_factor: number;
  due_date: string;
}

/** S1.10: due-today revision list. */
export interface RevisionDue {
  today: string;
  due_count: number;
  items: RevisionItemOut[];
}

/** S1.11: one global-search result row. */
export interface SearchHit {
  kind: "subject" | "chapter" | "question";
  title: string;
  subtitle: string | null;
  href: string;
  score: number;
}

/** S1.11: GET /search payload. */
export interface SearchResponse {
  query: string;
  ask_action: boolean;
  hits: SearchHit[];
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  grounded?: boolean | null;
  refused_reason?: string | null;
  sources: SourceRef[];
  // Wave 2: numeric confidence from the SSE done event
  confidence?: number | null;
  rating?: number | null;
  created_at?: string;
}

export interface ChatDoneEvent extends AskResponse {
  user_message_id: number;
  message_id: number;
}

export interface QuizQuestionPublic {
  id: string;
  question_text: string;
  options: string[];
}

// S4.5: KG-grounded re-teach card (prereq chapter excerpt, no AI text).
export interface ReteachCard {
  concept: string;
  prereq: string;
  depth: number;
  excerpt: string;
}

export interface QuizStarted {
  attempt_id: number;
  questions: QuizQuestionPublic[];
  requested: number;
  note?: string | null;
  reteach?: ReteachCard[] | null;
}

export interface ReviewItem {
  question_text: string;
  options: string[];
  chosen: number;
  correct_index: number;
  is_correct: boolean;
  chapter: string;
}

export interface QuizResult {
  attempt_id: number;
  score_pct: number;
  correct: number;
  total: number;
  review: ReviewItem[];
  reteach?: ReteachCard[] | null;
}

export interface ChapterStat {
  chapter: string;
  asked: number;
  correct: number;
  accuracy: number;
}

export interface StudentResponse {
  id: number;
  name: string;
  class_level: number;
}

export interface StudentProgress {
  student: StudentResponse;
  attempts_graded: number;
  avg_score_pct: number | null;
  by_chapter: ChapterStat[];
  weak_chapters: string[];
}

export interface StudentBrief {
  student_id: number;
  name: string;
  class_level: number;
  attempts_graded: number;
  avg_score_pct: number | null;
}

export interface ClassAnalytics {
  class_level: number;
  students: number;
  chapters: ChapterStat[];
  weak_chapters: string[];
  students_detail: StudentBrief[];
}

export interface UserPublic {
  id: number;
  email: string;
  role: string;
  created_at: string;
}

export interface AdminOverview {
  users_total: number;
  students: number;
  teachers: number;
  admins: number;
  parents: number;
  quiz_attempts_graded: number;
  avg_score_pct: number | null;
}

export interface AdminUsersPage {
  total: number;
  items: UserPublic[];
}

export interface RefusalAudit {
  days: number;
  total_refusals: number;
  by_reason: Record<string, number>;
  by_class: Record<string, number>;
  last_refusal_at: string | null;
}

export interface ContinueLearning {
  subject: string | null;
  chapter: string | null;
  class_level: number | null;
  excerpt: string | null;
}

export interface QuickAction {
  label: string;
  to: string;
  icon?: string | null;
}

export interface Recommendation {
  type: string;
  subject: string | null;
  chapter: string | null;
  reason: string | null;
}

export interface DashboardSummary {
  user: {
    user_id: number;
    email: string;
    role: string;
    profile_id: number | null;
    name: string | null;
    class_level: number | null;
  };
  today: string;
  continue_learning: ContinueLearning | null;
  quick_actions: QuickAction[];
  recommendation: Recommendation | null;
  progress: StudentProgress | null;
}

/* -------- Learn catalog (grounded corpus) -------- */
export interface SubjectOut {
  subject: string;
  book: string;
  class_levels: number[];
}

export interface ChapterSummaryOut {
  chapter: string;
  excerpt: string;
  section_count: number;
}

export interface SectionOut {
  section: string;
  text: string;
}

export interface ChapterContentOut {
  subject: string;
  class_level: number;
  book: string;
  chapter: string;
  sections: SectionOut[];
}

export interface ChapterProgressOut {
  subject: string;
  chapter: string;
  class_level: number;
  read_pct: number;
  completed: boolean;
  bookmarked: boolean;
  updated_at: string | null;
}

// S2.2: classroom management + CSV import.
export interface ClassRoom {
  id: number;
  class_level: number;
  section: string;
  student_count: number;
}

export interface RosterEntry {
  student_id: number;
  name: string;
  class_level: number;
  email: string | null;
  invite_pending: boolean;
  attempts_graded: number;
  avg_score_pct: number | null;
}

export interface ImportRow {
  name: string;
  email: string;
  status: string;
  invite_code: string | null;
}

export interface ImportResult {
  created: number;
  failed: number;
  rows: ImportRow[];
}

// S2.4: question paper builder (AI draft -> teacher review -> FINAL).
export interface QQuestion {
  ref: string;
  text: string;
  options: string[];
  answer_index: number;
  marks: number;
  difficulty: string;
  chapter: string;
  reviewed: boolean;
}

export interface QPaper {
  id: number;
  class_level: number;
  subject: string;
  exam_type: string;
  marks: number;
  duration_min: number;
  difficulty: { easy: number; medium: number; hard: number };
  chapters: string[];
  status: string; // draft | final
  questions: QQuestion[];
  meta: Record<string, unknown>;
  reviewed_at: string | null;
  finalized_at: string | null;
  created_at: string | null;
}

// S2.5: short tests -- one rule-based set assigned to a whole classroom.
export interface ShortTest {
  id: number;
  classroom_id: number;
  teacher_id: number;
  subject: string;
  chapter: string;
  num_questions: number;
  duration_min: number;
  questions: QuizQuestionPublic[];
  attempts: { student_id: number; attempt_id: number }[];
  created_at: string | null;
}

export interface ShortTestMine {
  id: number;
  classroom_id: number;
  attempt_id: number | null;
  subject: string;
  chapter: string;
  num_questions: number;
  duration_min: number;
  questions: QuizQuestionPublic[];
  created_at: string | null;
  expires_at: string | null;
  expired: boolean;
}

// S2.6: lesson plan copilot -- 8 AI-drafted sections, edited & printed in-app.
export interface LessonPlan {
  sections: Record<string, string>;
  sources: SourceRef[];
  class_level: number;
  subject: string;
  chapter: string;
  minutes: number;
  level: string;
}

// S2.7: weakness heatmap + rule-based at-risk flags + 3-week support plans.
export interface WeakCell {
  asked: number;
  correct: number;
  accuracy: number | null;
  read: boolean;
}

export interface WeakStudent {
  student_id: number;
  name: string;
  avg_score_pct: number | null;
  attempts_graded: number;
  trend: "up" | "down" | "flat";
  at_risk: boolean;
  /** S4.6 single-source weakness rollup (weakest first). */
  weak_concepts?: string[];
  cells: Record<string, WeakCell>;
}

export interface WeakMatrix {
  class_level: number;
  concepts: string[];
  students: WeakStudent[];
}

export interface SupportPlanWeek {
  week: number;
  stage: string;
  concepts: string[];
  action: string;
  detail: string;
}

export interface SupportPlanRow {
  id: number;
  student_id: number;
  teacher_id: number;
  class_level: number;
  focus_concepts: string[];
  plan: { weeks?: SupportPlanWeek[]; focus_concepts?: string[] };
  created_at: string | null;
}

// S2.8: bulk assignment -- one shared quiz, per-student tracking vs a due date.
export interface AssignmentRow {
  id: number;
  teacher_id: number;
  subject: string;
  chapter: string;
  num_questions: number;
  due_at: string;
  questions: QuizQuestionPublic[];
  attempts: { student_id: number; attempt_id: number }[];
  created_at: string | null;
}

export interface AssignmentProgressRow {
  student_id: number;
  name: string;
  attempt_id: number;
  done: boolean;
  score_pct: number | null;
  overdue: boolean;
}

export interface AssignmentMine {
  id: number;
  attempt_id: number;
  subject: string;
  chapter: string;
  questions: QuizQuestionPublic[];
  due_at: string;
  overdue: boolean;
  done: boolean;
}

// S3.2 school dashboard
export interface SchoolAtRiskRow {
  student_id: number;
  name: string;
  class_level: number;
  section: string;
  attempts_graded: number;
  avg_score_pct: number | null;
  trend: string;
}

export interface SchoolHealth {
  school_id: number;
  name: string;
  code: string;
  students: number;
  teachers: number;
  classrooms: number;
  sessions_7d: number;
  strong: number;
  support: number;
  risk: number;
  ungraded: number;
  strong_pct: number;
  support_pct: number;
  risk_pct: number;
  at_risk: SchoolAtRiskRow[];
}

// S3.3: class x subject curriculum coverage grid.
export interface CoverageCellData {
  classroom_id: number;
  class_level: number;
  section: string;
  subject: string;
  taught: boolean;
  attempts: number;
  attempts_graded: number;
  avg_score_pct: number | null;
  status: string;
}

export interface Coverage {
  subjects: string[];
  cells: CoverageCellData[];
}

// S3.5: admin center v1.5 -- per-school stats, content versions, invite admin.
export interface AdminSchoolStats {
  id: number;
  name: string;
  code: string;
  created_at: string;
  teachers: number;
  classrooms: number;
  students: number;
  sessions_7d: number;
}

export interface ContentVersionRow {
  subject: string;
  class_level: number;
  chapter: string;
  current_version: number;
  versions_total: number;
  source: string;
  updated_at: string | null;
  updated_by_email: string | null;
}

export interface SchoolInviteAdmin {
  id: number;
  school_id: number;
  role: string;
  used: boolean;
  created_at: string;
  used_at: string | null;
}

// S5.10: feedback triage queue (admin view; reporter identity withheld by design).
export interface FeedbackAdminRow {
  id: number;
  user_id: number;
  role: string;
  rating: number;
  comment: string | null;
  message_id: number | null;
  attempt_id: number | null;
  triaged: boolean;
  triaged_at: string | null;
  note: string | null;
  created_at: string;
}

export interface FeedbackQueuePage {
  rows: FeedbackAdminRow[];
  total: number;
  open_count: number;
  limit: number;
  offset: number;
}

// S5.10: public status page -- presence/booleans only, never usage counts.
export interface StatusComponent {
  name: string;
  ok: boolean;
  detail: string;
}

export interface StatusOut {
  status: string;
  components: StatusComponent[];
  checked_at: string;
}
