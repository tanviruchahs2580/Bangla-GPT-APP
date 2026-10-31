import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ClipboardCheck, Repeat2, Target } from "lucide-react";
import { get, post } from "../../api";
import { track } from "../../lib/analytics";
import type {
  AssignmentMine,
  DashboardSummary,
  QuizResult,
  QuizStarted,
  RevisionDue,
  RevisionItemOut,
  ShortTestMine,
  StudentProgress,
} from "../../types";
import { invalidateStudyCaches } from "../../lib/invalidate";
import { buildExplainPayload, LAST_RESULT_KEY } from "../../lib/quizExplain";
import { useAuth } from "../../AuthContext";
import { Badge, Button, Card } from "../../components/ui";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";
import { cn } from "../../lib/cn";
import {
  clearQuizDraft,
  readQuizDraft,
  QUIZ_DRAFT_KEY,
} from "../../lib/quizDraft";
import { AssignedPanel, type AssignedEntry } from "./quiz/AssignedPanel";
import { QuizResultScreen } from "./quiz/QuizResultScreen";
import { QuizRunner } from "./quiz/QuizRunner";
import { RevisionPanel } from "./quiz/RevisionPanel";
import { StartQuizCard, subjectOptions } from "./quiz/StartQuizCard";

/**
 * F-094 split: the screens and tab panels live under ./quiz/ now. This file
 * keeps the state that spans them (the draft, the answer map, the submit
 * guard, the hub tabs, the queries) and the wiring between them.
 */
export default function QuizPage() {
  const { me } = useAuth();
  const isStudent = me?.role === "student";
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [number, setNumber] = useState<string>(
    // ?count=3 from the home page's "mini quiz" tile; otherwise the 5 default.
    searchParams.get("count") ?? "5",
  );
  // the tutor's quiz chip preselects the subject via ?subject=.
  const [subject, setSubject] = useState<string>(
    searchParams.get("subject") ?? subjectOptions()[0].value,
  );
  // B-03: restored from the draft, a reload drops the student back into the
  // exact question they were on with every answer intact.
  const [started, setStarted] = useState<QuizStarted | null>(
    () => readQuizDraft()?.started ?? null,
  );
  const [answers, setAnswers] = useState<Record<number, number>>(
    () => readQuizDraft()?.answers ?? {},
  );
  const [current, setCurrent] = useState<number>(
    () => readQuizDraft()?.current ?? 0,
  );
  const [result, setResult] = useState<QuizResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // B-03: "Finish" with unanswered questions used to submit them all as
  // wrong with no warning — a child tapping Finish on question 1 of 10 saw
  // a confident 0%. Confirm first, announce via role="alert".
  const [confirmSubmit, setConfirmSubmit] = useState(false);

  // B-03: write-through draft — every answered question is durable within
  // the tab before the next render matters, and a successful submit (or a
  // fresh start) replaces/clears it via the same effect.
  useEffect(() => {
    try {
      if (started)
        sessionStorage.setItem(
          QUIZ_DRAFT_KEY,
          JSON.stringify({ started, answers, current }),
        );
      else clearQuizDraft();
    } catch {
      /* storage may be unavailable in low-data/incognito mode */
    }
  }, [started, answers, current]);

  const unanswered = started
    ? started.questions.reduce(
        (n, _, i) => n + (answers[i] === undefined ? 1 : 0),
        0,
      )
    : 0;

  const requestSubmit = () => {
    if (unanswered > 0 && !confirmSubmit) {
      setConfirmSubmit(true);
      return;
    }
    setConfirmSubmit(false);
    void submit();
  };

  const queryClient = useQueryClient();
  const { data: progress } = useQuery({
    queryKey: ["progress", me?.profile_id],
    queryFn: () => {
      if (!me?.profile_id) throw new Error("student profile is not loaded");
      return get<StudentProgress>(`/students/${me.profile_id}/progress`);
    },
    enabled: !!me?.profile_id && me.role === "student",
  });
  const { data: dashboard } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => get<DashboardSummary>("/dashboard/summary"),
    enabled: me?.role === "student",
  });

  // spaced-revision tab (SM-2-lite queue) with due badge.
  const [tab, setTab] = useState<"quiz" | "revision" | "assigned">("quiz");
  const { data: due, refetch: refetchDue } = useQuery({
    queryKey: ["revision-due"],
    queryFn: () => get<RevisionDue>("/revision/due"),
    enabled: me?.role === "student",
  });
  // FE-06: the visual tabs promise tab semantics, so the keyboard gets
  // them too — roving focus with arrow keys, exactly the contract
  // LearnPage implements for the same controls.
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const tabOrder = ["quiz", "revision", "assigned"] as const;
  const onTablistKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const idx = tabOrder.indexOf(tab);
    const next =
      e.key === "ArrowRight"
        ? tabOrder[(idx + 1) % tabOrder.length]
        : e.key === "ArrowLeft"
          ? tabOrder[(idx + tabOrder.length - 1) % tabOrder.length]
          : null;
    if (next === null) return;
    e.preventDefault();
    setTab(next);
    tabRefs.current[tabOrder.indexOf(next)]?.focus();
  };

  // + merged "assigned by teacher" list (short tests + bulk).
  const {
    data: stMine,
    isPending: stMinePending,
    isError: stMineFailed,
    refetch: refetchStMine,
  } = useQuery({
    queryKey: ["shorttests-mine"],
    queryFn: () => get<ShortTestMine[]>("/shorttests/mine"),
    enabled: me?.role === "student",
  });
  const {
    data: asMine,
    isPending: asMinePending,
    isError: asMineFailed,
    refetch: refetchAsMine,
  } = useQuery({
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
    setConfirmSubmit(false);
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

  // restore the last graded result when returning from the tutor explain flow.
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
    // Captured after the guard: TypeScript cannot narrow `started` across the
    // awaits below, and a non-null assertion would hide a real null.
    const attempt = started;
    if (!attempt) return;
    setBusy(true);
    try {
      const res = await post<QuizResult>(
        `/quizzes/${attempt.attempt_id}/submit`,
        {
          answers: attempt.questions.map((_, i) => answers[i] ?? -1),
        },
      );
      setResult(res);
      setStarted(null);
      setConfirmSubmit(false);
      // The submit is what the streak, average and heatmap are derived from;
      // without this the hub behind the result screen renders pre-quiz
      // numbers for the whole staleTime window.
      invalidateStudyCaches(queryClient);
      track("quiz_completed", {
        score_pct: res.score_pct,
        correct: res.correct,
        total: res.total,
      });
      // keep the result for the tutor explain back-link (?result=1).
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
      <QuizResultScreen
        result={result}
        onExplain={(row) =>
          navigate("/student/tutor", {
            state: { explain: buildExplainPayload(row), backToResult: true },
          })
        }
        onRestart={() => {
          setResult(null);
          void start();
        }}
      />
    );
  }

  // ----- in-progress quiz -----
  if (started) {
    return (
      <QuizRunner
        started={started}
        current={current}
        answers={answers}
        busy={busy}
        error={error}
        confirmSubmit={confirmSubmit}
        unanswered={unanswered}
        onChoose={(oi) => setAnswers((a) => ({ ...a, [current]: oi }))}
        onPrevious={() => setCurrent((c) => c - 1)}
        onNext={() => setCurrent((c) => c + 1)}
        onRequestSubmit={requestSubmit}
        onSubmitAnyway={() => {
          setConfirmSubmit(false);
          void submit();
        }}
        onKeepAnswering={() => setConfirmSubmit(false)}
      />
    );
  }

  // ----- practice hub start screen -----
  const weakChapters = progress?.weak_chapters ?? [];
  const rec = dashboard?.recommendation;
  const assigned: AssignedEntry[] = [
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
    <main id="main-content" tabIndex={-1} className="shell-main">
      <section className="section-head">
        <h1>{t("practiceTitle")}</h1>
      </section>

      {/* আমার দুর্বলতা — the most prominent entry, from the weakness rollup */}
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
        tabIndex={-1}
        onKeyDown={onTablistKeyDown}
      >
        <button
          role="tab"
          aria-selected={tab === "quiz"}
          tabIndex={tab === "quiz" ? 0 : -1}
          ref={(el) => {
            tabRefs.current[0] = el;
          }}
          className={cn("chip", tab === "quiz" && "active")}
          onClick={() => setTab("quiz")}
        >
          {t("chapterPracticeTab")}
        </button>
        <button
          role="tab"
          aria-selected={tab === "revision"}
          tabIndex={tab === "revision" ? 0 : -1}
          ref={(el) => {
            tabRefs.current[1] = el;
          }}
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
          tabIndex={tab === "assigned" ? 0 : -1}
          ref={(el) => {
            tabRefs.current[2] = el;
          }}
          className={cn("chip", tab === "assigned" && "active")}
          onClick={() => setTab("assigned")}
        >
          <ClipboardCheck size={14} aria-hidden /> {t("teacherAssignedTab")}
          {assigned.length > 0 && <Badge tone="teal">{assigned.length}</Badge>}
        </button>
      </div>

      {tab === "revision" ? (
        <RevisionPanel
          due={due}
          busy={revisionBusy}
          error={error}
          onAnswer={(item, oi) => void answerRevision(item, oi)}
        />
      ) : tab === "assigned" ? (
        <AssignedPanel
          assigned={assigned}
          isStudent={isStudent}
          shortTestPending={stMinePending}
          assignmentsPending={asMinePending}
          shortTestFailed={stMineFailed}
          assignmentsFailed={asMineFailed}
          onRetry={() => {
            if (stMineFailed) void refetchStMine();
            if (asMineFailed) void refetchAsMine();
          }}
          onOpenShortTest={openShortTest}
          onOpenAssigned={openAssigned}
        />
      ) : (
        <StartQuizCard
          number={number}
          subject={subject}
          onNumberChange={setNumber}
          onSubjectChange={setSubject}
          progress={progress}
          error={error}
          busy={busy}
          canStart={!!me?.profile_id}
          onStart={() => void start()}
        />
      )}
    </main>
  );
}
