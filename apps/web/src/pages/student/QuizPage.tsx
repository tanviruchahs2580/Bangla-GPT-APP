import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ClipboardCheck,
  RefreshCcw,
  Repeat2,
  Target,
} from "lucide-react";
import { get, post } from "../../api";
import { track } from "../../lib/analytics";
import type {
  AssignmentMine,
  DashboardSummary,
  QuizResult,
  QuizStarted,
  ReteachCard,
  RevisionDue,
  RevisionItemOut,
  ShortTestMine,
  StudentProgress,
} from "../../types";
import { buildExplainPayload, LAST_RESULT_KEY } from "../../lib/quizExplain";
import { useAuth } from "../../AuthContext";
import { Badge, Button, Card, ProgressRing, Stat } from "../../components/ui";
import { friendlyError } from "../../errors";
import { t, tSubject } from "../../i18n";
import { cn } from "../../lib/cn";
import { celebrate } from "../../lib/confetti";

// RENO: labels from i18n, evaluated per render (lang switch remounts).
const subjectOptions = () => [
  { value: "science", label: t("subjectScience") },
  { value: "mathematics", label: t("subjectMath") },
  { value: "bangla", label: t("subjectBangla") },
];

// S4.5: KG gap -> grounded re-teach card (textbook excerpt, never AI text).
function QuizCelebration({ score }: { score: number }) {
  useEffect(() => {
    celebrate(score);
  }, [score]);
  return null;
}

function ReteachCards({ cards }: { cards: ReteachCard[] }) {
  if (cards.length === 0) return null;
  return (
    <Card className="reteach-card card-ai">
      <div className="card-title">{t("reteachTitle")}</div>
      <p className="muted muted-sm reteach-hint">{t("reteachHint")}</p>
      <div className="stack">
        {cards.map((c, i) => (
          <div key={i} className="reteach-item">
            <div className="row-title">
              {t("reteachChain", { concept: c.concept, prereq: c.prereq })}
            </div>
            <p className="reteach-excerpt">{c.excerpt}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function QuizPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [number, setNumber] = useState<string>("5");
  // S1.4: the tutor's quiz chip preselects the subject via ?subject=.
  const [subject, setSubject] = useState<string>(
    searchParams.get("subject") ?? subjectOptions()[0].value,
  );
  const [started, setStarted] = useState<QuizStarted | null>(null);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [current, setCurrent] = useState(0);
  const [result, setResult] = useState<QuizResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: progress } = useQuery({
    queryKey: ["progress", me?.profile_id],
    queryFn: () => get<StudentProgress>(`/students/${me!.profile_id}/progress`),
    enabled: !!me?.profile_id && me.role === "student",
  });
  const { data: dashboard } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => get<DashboardSummary>("/dashboard/summary"),
    enabled: me?.role === "student",
  });

  // S1.10: spaced-revision tab (SM-2-lite queue) with due badge.
  const [tab, setTab] = useState<"quiz" | "revision" | "assigned">("quiz");
  const { data: due, refetch: refetchDue } = useQuery({
    queryKey: ["revision-due"],
    queryFn: () => get<RevisionDue>("/revision/due"),
    enabled: me?.role === "student",
  });
  // S2.5 + S2.8 merged "assigned by teacher" list (short tests + bulk).
  const { data: stMine } = useQuery({
    queryKey: ["shorttests-mine"],
    queryFn: () => get<ShortTestMine[]>("/shorttests/mine"),
    enabled: me?.role === "student",
  });
  const { data: asMine } = useQuery({
    queryKey: ["assignments-mine"],
    queryFn: () => get<AssignmentMine[]>("/assignments/mine"),
    enabled: me?.role === "student",
  });

  const openShortTest = (st: ShortTestMine) => {
    if (st.attempt_id === null) return;
    setStarted({
      attempt_id: st.attempt_id,
      questions: st.questions,
      requested: st.num_questions,
    });
    setAnswers({});
    setCurrent(0);
    setResult(null);
  };
  const openAssigned = (a: AssignmentMine) => {
    if (a.done) return;
    setStarted({
      attempt_id: a.attempt_id,
      questions: a.questions,
      requested: a.questions.length,
    });
    setAnswers({});
    setCurrent(0);
    setResult(null);
  };
  const [revisionBusy, setRevisionBusy] = useState(false);

  const answerRevision = async (item: RevisionItemOut, chosen: number) => {
    setRevisionBusy(true);
    setError(null);
    try {
      await post(`/revision/${item.id}/review`, { chosen });
      await refetchDue();
    } catch (e) {
      setError(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setRevisionBusy(false);
    }
  };

  // S1.7: restore the last graded result when returning from the tutor explain flow.
  useEffect(() => {
    if (searchParams.get("result") !== "1") return;
    try {
      const raw = sessionStorage.getItem(LAST_RESULT_KEY);
      if (raw) setResult(JSON.parse(raw) as QuizResult);
    } catch {
      /* stale cache — start screen is fine */
    }
  }, [searchParams]);

  const start = async (opts?: {
    subject?: string;
    chapter?: string;
    count?: number;
  }) => {
    setBusy(true);
    setError(null);
    const useSubject = opts?.subject ?? subject;
    try {
      const res = await post<QuizStarted>("/quizzes", {
        student_id: me?.profile_id,
        class_level: me?.class_level ?? 6,
        subject: useSubject,
        ...(opts?.chapter ? { chapter: opts.chapter } : {}),
        num_questions: Math.min(
          20,
          Math.max(1, Number(opts?.count ?? number) || 5),
        ),
      });
      setStarted(res);
      setAnswers({});
      setCurrent(0);
      setResult(null);
      track("quiz_started", { subject: useSubject, n: res.questions.length });
    } catch (e) {
      setError(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    setBusy(true);
    try {
      const res = await post<QuizResult>(
        `/quizzes/${started!.attempt_id}/submit`,
        {
          answers: started!.questions.map((_, i) => answers[i] ?? -1),
        },
      );
      setResult(res);
      setStarted(null);
      track("quiz_completed", {
        score_pct: res.score_pct,
        correct: res.correct,
        total: res.total,
      });
      // S1.7: keep the result for the tutor explain back-link (?result=1).
      try {
        sessionStorage.setItem(LAST_RESULT_KEY, JSON.stringify(res));
      } catch {
        /* storage may be unavailable in low-data/incognito mode */
      }
    } catch (e) {
      setError(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setBusy(false);
    }
  };

  // ----- result screen -----
  if (result) {
    return (
      <main className="shell-main">
        <section className="section-head">
          <h2>{t("yourQuizResult")}</h2>
        </section>
        <QuizCelebration score={result.score_pct} />
        <Card className="card-featured">
          <div className="row-flex quiz-result-hero">
            <ProgressRing
              value={result.score_pct}
              size={120}
              label={<strong>{Math.round(result.score_pct)}%</strong>}
            />
            <div className="stat-value quiz-result-score">
              {t("correctOutOf", {
                correct: result.correct,
                total: result.total,
              })}
            </div>
          </div>
          <div className="stack section-gap-top">
            {result.review.map((r, i) => (
              <Card key={i} className="row quiz-review-row">
                <span
                  className={cn(
                    "quick-icon",
                    r.is_correct ? "tile-ok" : "tile-danger",
                  )}
                >
                  {r.is_correct ? (
                    <Check size={18} aria-hidden />
                  ) : (
                    <ClipboardCheck size={18} aria-hidden />
                  )}
                </span>
                <div className="row-main">
                  <div className="row-title">{r.question_text}</div>
                  <div className="row-sub">
                    {t("chapter")}: {r.chapter} —{" "}
                    {r.options[r.correct_index] ?? ""}
                  </div>
                  {!r.is_correct && (
                    // S1.7: wrong item → explain loop with full quiz context.
                    <Button
                      variant="ghost"
                      size="sm"
                      className="section-gap-top"
                      onClick={() =>
                        navigate("/student/tutor", {
                          state: {
                            explain: buildExplainPayload(r),
                            backToResult: true,
                          },
                        })
                      }
                    >
                      {t("explainThis")}
                    </Button>
                  )}
                </div>
              </Card>
            ))}
          </div>
        </Card>
        {result.reteach && result.reteach.length > 0 && (
          <div className="section-gap-top">
            <ReteachCards cards={result.reteach} />
          </div>
        )}
        {/* one clear next step; everything else is secondary */}
        <div className="section-gap-top">
          <Button
            variant="primary"
            block
            onClick={() => {
              setResult(null);
              void start();
            }}
          >
            <RefreshCcw size={18} aria-hidden /> {t("startQuiz")}
          </Button>
        </div>
      </main>
    );
  }

  // ----- in-progress quiz -----
  if (started) {
    const q = started.questions[current];
    const chosen = answers[current];
    const answeredCount = Object.keys(answers).length;
    return (
      <main className="shell-main">
        <section className="section-head">
          <h2>{t("practiceTitle")}</h2>
          <Badge>
            {current + 1}/{started.questions.length}
          </Badge>
        </section>
        {started.reteach && started.reteach.length > 0 && current === 0 && (
          <div className="stack chips-gap">
            <ReteachCards cards={started.reteach} />
          </div>
        )}
        <Card key={current} className="quiz-q">
          <div className="row-flex chips-gap">
            <ProgressRing
              value={(answeredCount / started.questions.length) * 100}
              size={64}
              label={
                <strong>
                  {answeredCount}/{started.questions.length}
                </strong>
              }
            />
            <div className="row-main">
              <div className="row-title quiz-q-title">{q.question_text}</div>
              <div className="muted muted-sm">{t("chooseAnswers")}</div>
            </div>
          </div>
          <div className="stack" role="radiogroup" aria-label={q.question_text}>
            {q.options.map((opt, oi) => (
              <button
                key={oi}
                role="radio"
                aria-checked={chosen === oi}
                className={cn("quiz-option", chosen === oi && "selected")}
                onClick={() => setAnswers((a) => ({ ...a, [current]: oi }))}
              >
                {opt}
              </button>
            ))}
          </div>
          <div className="row-flex quiz-pager">
            <Button
              variant="ghost"
              size="sm"
              disabled={current === 0}
              onClick={() => setCurrent((c) => c - 1)}
            >
              <ArrowLeft size={16} aria-hidden /> {t("previousQuestion")}
            </Button>
            {current < started.questions.length - 1 ? (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setCurrent((c) => c + 1)}
              >
                {t("nextQuestion")} <ArrowRight size={16} aria-hidden />
              </Button>
            ) : (
              <Button variant="teal" size="sm" onClick={submit} disabled={busy}>
                {t("finishQuiz")}
              </Button>
            )}
          </div>
          {error && <p className="error section-gap-top">{error}</p>}
        </Card>
      </main>
    );
  }

  // ----- practice hub start screen -----
  const avg = progress?.avg_score_pct;
  const weakChapters = progress?.weak_chapters ?? [];
  const rec = dashboard?.recommendation;
  const assigned: Array<
    | { kind: "shorttest"; item: ShortTestMine }
    | { kind: "bulk"; item: AssignmentMine }
  > = [
    ...(Array.isArray(stMine) ? stMine : []).map((item) => ({
      kind: "shorttest" as const,
      item,
    })),
    ...(Array.isArray(asMine) ? asMine : []).map((item) => ({
      kind: "bulk" as const,
      item,
    })),
  ].sort((a, b) => {
    // open work first, then done/expired history
    const openA = a.kind === "shorttest" ? !a.item.expired : !a.item.done;
    const openB = b.kind === "shorttest" ? !b.item.expired : !b.item.done;
    if (openA !== openB) return openA ? -1 : 1;
    return 0;
  });

  return (
    <main className="shell-main">
      <section className="section-head">
        <h2>{t("practiceTitle")}</h2>
      </section>

      {/* 🎯 আমার দুর্বলতা — the most prominent entry, from the weakness rollup */}
      <Card className="practice-weak-card card-featured">
        <div className="row-flex">
          <span className="quick-icon tile-warn" aria-hidden>
            <Target size={22} />
          </span>
          <div className="row-main">
            <div className="row-title">{t("weakPracticeTitle")}</div>
            <div className="row-sub">{t("weakPracticeHint")}</div>
            <div className="chips section-gap-top">
              {weakChapters.length === 0 && (
                <span className="muted muted-sm">{t("noWeakChapters")}</span>
              )}
              {weakChapters.slice(0, 4).map((w) => (
                <span key={w} className="badge badge-warn">
                  {w}
                </span>
              ))}
            </div>
          </div>
        </div>
        {rec?.chapter && (
          <Button
            variant="primary"
            className="section-gap-top"
            loading={busy}
            onClick={() =>
              void start({
                subject: rec.subject ?? subject,
                chapter: rec.chapter ?? undefined,
                count: 3,
              })
            }
          >
            <Target size={18} aria-hidden /> {t("weakPracticeStart")}
          </Button>
        )}
        {error && <p className="error section-gap-top">{error}</p>}
      </Card>

      <div
        className="chips chips-gap"
        role="tablist"
        aria-label={t("practiceTitle")}
      >
        <button
          role="tab"
          aria-selected={tab === "quiz"}
          className={cn("chip", tab === "quiz" && "active")}
          onClick={() => setTab("quiz")}
        >
          {t("chapterPracticeTab")}
        </button>
        <button
          role="tab"
          aria-selected={tab === "revision"}
          className={cn("chip", tab === "revision" && "active")}
          onClick={() => setTab("revision")}
        >
          <Repeat2 size={14} aria-hidden /> {t("revisionTab")}
          {due && due.due_count > 0 && (
            <Badge tone="teal">{due.due_count}</Badge>
          )}
        </button>
        <button
          role="tab"
          aria-selected={tab === "assigned"}
          className={cn("chip", tab === "assigned" && "active")}
          onClick={() => setTab("assigned")}
        >
          <ClipboardCheck size={14} aria-hidden /> {t("teacherAssignedTab")}
          {assigned.length > 0 && <Badge tone="teal">{assigned.length}</Badge>}
        </button>
      </div>

      {tab === "revision" ? (
        <div className="stack">
          {due && due.items.length === 0 && (
            <Card>
              <p className="muted flush">{t("revisionEmpty")}</p>
            </Card>
          )}
          {due?.items.map((item) => (
            <Card key={item.id} className="row quiz-review-row">
              <div className="row-main">
                <div className="row-title">{item.question}</div>
                <div className="row-sub">
                  {t("chapter")}: {item.chapter}
                </div>
                <div className="stack section-gap-top">
                  {item.options.map((opt, oi) => (
                    <button
                      key={oi}
                      className="quiz-option"
                      disabled={revisionBusy}
                      onClick={() => answerRevision(item, oi)}
                    >
                      {opt}
                    </button>
                  ))}
                  <p className="muted muted-sm flush">{t("revisionChoose")}</p>
                </div>
              </div>
            </Card>
          ))}
          {error && <p className="error">{error}</p>}
        </div>
      ) : tab === "assigned" ? (
        <div className="stack">
          {assigned.length === 0 && (
            <Card>
              <p className="muted flush">{t("assignedEmpty")}</p>
            </Card>
          )}
          {assigned.map(({ kind, item }) => {
            if (kind === "shorttest") {
              const st = item;
              return (
                <Card key={`st-${st.id}`} className="row quiz-review-row">
                  <div className="row-main">
                    <div className="row-title">
                      <Badge tone="teal">{t("assignedShortTest")}</Badge>{" "}
                      {st.chapter}
                    </div>
                    <div className="row-sub">
                      {tSubject(st.subject)} ·{" "}
                      {t("stMinutes", { n: st.duration_min })}
                      {st.expired && (
                        <Badge tone="warn"> {t("stExpired")}</Badge>
                      )}
                    </div>
                    <Button
                      variant="primary"
                      size="sm"
                      className="section-gap-top"
                      disabled={st.attempt_id === null || st.expired}
                      onClick={() => openShortTest(st)}
                    >
                      {t("startQuiz")}
                    </Button>
                  </div>
                </Card>
              );
            }
            const a = item;
            return (
              <Card key={`ba-${a.id}`} className="row quiz-review-row">
                <div className="row-main">
                  <div className="row-title">
                    <Badge>{t("assignedBulk")}</Badge> {a.chapter}
                  </div>
                  <div className="row-sub">
                    {tSubject(a.subject)} · {t("baDue")}:{" "}
                    {new Date(a.due_at).toLocaleString()}
                    {a.done ? (
                      <Badge tone="ok"> {t("baDone")}</Badge>
                    ) : a.overdue ? (
                      <Badge tone="warn"> {t("baOverdue")}</Badge>
                    ) : null}
                  </div>
                  <Button
                    variant="primary"
                    size="sm"
                    className="section-gap-top"
                    disabled={a.done}
                    onClick={() => openAssigned(a)}
                  >
                    {t("startQuiz")}
                  </Button>
                </div>
              </Card>
            );
          })}
        </div>
      ) : (
        <Card>
          <div className="card-title">{t("startQuiz")}</div>
          <div className="field">
            <label htmlFor="qcount">{t("questionCount")}</label>
            <select
              id="qcount"
              className="select"
              value={number}
              onChange={(e) => setNumber(e.target.value)}
            >
              {[3, 5, 10, 15].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="quiz-subject">{t("subject")}</label>
            <select
              id="quiz-subject"
              className="select"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            >
              {subjectOptions().map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          {progress && progress.attempts_graded > 0 && (
            <div className="stat-grid section-gap-top">
              <Stat value={Math.round(avg ?? 0) + "%"} label={t("avgScore")} />
              <Stat
                value={progress.attempts_graded}
                label={t("gradedQuizzes")}
              />
            </div>
          )}
          {error && <p className="error">{error}</p>}
          <Button
            variant="primary"
            block
            onClick={() => void start()}
            disabled={busy || !me?.profile_id}
          >
            {t("startQuiz")}
          </Button>
          {!me?.profile_id && (
            <p className="muted muted-sm section-gap-top">{t("notStarted")}</p>
          )}
        </Card>
      )}
    </main>
  );
}
