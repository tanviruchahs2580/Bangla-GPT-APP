import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  BookOpen,
  ClipboardList,
  FileText,
  HelpCircle,
  ListChecks,
  NotebookPen,
  ScrollText,
  Timer,
} from "lucide-react";
import { get, post } from "../../api";
import type { LessonPlan, QPaper, ShortTest } from "../../types";
import { Button, Card, Field } from "../../components/ui";
import { CreateHub } from "../../components/teacher/CreateHub";
import { QPaperReviewPanel } from "../../components/teacher/QPaperReviewPanel";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";

const errText = (err: unknown): string =>
  friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
  t("errorGeneric");

// Grid entry -> deep-link token (shared with TeacherHome quick-create).
export type CreateEntry =
  | "question_paper"
  | "short_test"
  | "lesson_plan"
  | "worksheet"
  | "answer_key"
  | "homework"
  | "rubric"
  | "quiz";

const ENTRIES: Array<{
  kind: CreateEntry;
  label: string;
  sub?: string;
  icon: typeof FileText;
}> = [
  { kind: "question_paper", label: "qpTitle", icon: FileText },
  { kind: "short_test", label: "stTitle", icon: Timer },
  { kind: "lesson_plan", label: "lpTitle", icon: NotebookPen },
  {
    kind: "worksheet",
    label: "genWorksheet",
    sub: "cWorksheetSub",
    icon: BookOpen,
  },
  { kind: "quiz", label: "cQuizEntry", icon: ClipboardList },
  { kind: "answer_key", label: "genAnswerKey", icon: ListChecks },
  { kind: "homework", label: "genHomework", icon: HelpCircle },
  { kind: "rubric", label: "genRubric", icon: ScrollText },
];

const LESSON_SECTION_LABELS: Record<string, string> = {
  objective: "lpSecObjective",
  previous_knowledge: "lpSecPrevious",
  introduction: "lpSecIntro",
  main_explanation: "lpSecMain",
  activity: "lpSecActivity",
  questions: "lpSecQuestions",
  assessment: "lpSecAssessment",
  homework: "lpSecHomework",
};

// Quick mode first: never show a first-time teacher every setting at once.
function QuickAdvanced({
  advanced,
  onToggle,
}: {
  advanced: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className="chips mode-toggle"
      role="group"
      aria-label={t("cAdvancedMode")}
    >
      <button
        className={`chip${!advanced ? " active" : ""}`}
        aria-pressed={!advanced}
        onClick={() => onToggle()}
        disabled={!advanced}
      >
        {t("cQuickMode")}
      </button>
      <button
        className={`chip${advanced ? " active" : ""}`}
        aria-pressed={advanced}
        onClick={() => onToggle()}
        disabled={advanced}
      >
        {t("cAdvancedMode")}
      </button>
    </div>
  );
}

function QuestionPaperFlow() {
  const [advanced, setAdvanced] = useState(false);
  const [level, setLevel] = useState(() => {
    const v = localStorage.getItem("bgpt_teacher_default_class");
    return v ? Number(v) || 6 : 6;
  });
  const [subject, setSubject] = useState("science");
  const [examType, setExamType] = useState("");
  const [chapters, setChapters] = useState("");
  const [marks, setMarks] = useState(10);
  const [duration, setDuration] = useState(10);
  const [easy, setEasy] = useState(30);
  const [medium, setMedium] = useState(50);
  const [hard, setHard] = useState(20);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [qp, setQp] = useState<QPaper | null>(null);

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const res = await post<QPaper>("/teacher/qpapers", {
        class_level: level,
        subject,
        chapters: chapters
          .split(",")
          .map((c) => c.trim())
          .filter(Boolean),
        exam_type: examType,
        marks,
        duration_min: duration,
        difficulty: { easy, medium, hard },
      });
      setQp(res);
      setMsg(t("qpDraftReady"));
    } catch (err) {
      setMsg(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <Card>
        <div className="card-title">{t("qpTitle")}</div>
        <QuickAdvanced
          advanced={advanced}
          onToggle={() => setAdvanced((a) => !a)}
        />
        <form onSubmit={generate} className="grid-2 section-gap-top">
          <Field label={t("qpExamType")} htmlFor="qpexam">
            <input
              id="qpexam"
              className="input"
              value={examType}
              maxLength={40}
              onChange={(e) => setExamType(e.target.value)}
            />
          </Field>
          <Field
            label={t("className").replace(/\s*\(.*\)/, "")}
            htmlFor="qplvl"
          >
            <select
              id="qplvl"
              className="select"
              value={level}
              onChange={(e) => setLevel(Number(e.target.value))}
            >
              {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("subject")} htmlFor="qpsubj">
            <select
              id="qpsubj"
              className="select"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            >
              <option value="science">{t("subjectScience")}</option>
              <option value="math">{t("subjectMath")}</option>
              <option value="bangla">{t("subjectBangla")}</option>
            </select>
          </Field>
          <Field
            label={t("qpChaptersLabel")}
            htmlFor="qpchapters"
            className="form-grid-span"
          >
            <input
              id="qpchapters"
              className="input"
              value={chapters}
              onChange={(e) => setChapters(e.target.value)}
            />
          </Field>
          {advanced && (
            <>
              <Field label={t("qpMarks")} htmlFor="qpmarks">
                <input
                  id="qpmarks"
                  className="input"
                  type="number"
                  min={5}
                  max={100}
                  value={marks}
                  onChange={(e) => setMarks(Number(e.target.value))}
                />
              </Field>
              <Field label={t("qpDuration")} htmlFor="qpdur">
                <input
                  id="qpdur"
                  className="input"
                  type="number"
                  min={5}
                  max={300}
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                />
              </Field>
              <Field label={t("qpEasy")} htmlFor="qpeasy">
                <input
                  id="qpeasy"
                  className="input"
                  type="number"
                  min={0}
                  max={100}
                  value={easy}
                  onChange={(e) => setEasy(Number(e.target.value))}
                />
              </Field>
              <Field label={t("qpMedium")} htmlFor="qpmedium">
                <input
                  id="qpmedium"
                  className="input"
                  type="number"
                  min={0}
                  max={100}
                  value={medium}
                  onChange={(e) => setMedium(Number(e.target.value))}
                />
              </Field>
              <Field label={t("qpHard")} htmlFor="qphard">
                <input
                  id="qphard"
                  className="input"
                  type="number"
                  min={0}
                  max={100}
                  value={hard}
                  onChange={(e) => setHard(Number(e.target.value))}
                />
              </Field>
            </>
          )}
          <div className="form-grid-span">
            <Button
              variant="primary"
              type="submit"
              loading={busy}
              disabled={!examType.trim() || !chapters.trim()}
            >
              {t("qpGenerate")}
            </Button>
          </div>
        </form>
        {msg && (
          <p
            role="status"
            className={msg === t("errorGeneric") ? "error" : "muted"}
          >
            {msg}
          </p>
        )}
      </Card>
      {qp && <QPaperReviewPanel qp={qp} onChange={setQp} />}
    </div>
  );
}

export function ShortTestFlow() {
  const [advanced, setAdvanced] = useState(false);
  const [chapter, setChapter] = useState("");
  const [subject, setSubject] = useState("science");
  const [num, setNum] = useState(5);
  const [duration, setDuration] = useState(10);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [tests, setTests] = useState<ShortTest[]>([]);
  const [roomId, setRoomId] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    get<{ id: number }[]>("/teacher/classrooms")
      .then((rs) => {
        if (live) setRoomId(rs[0]?.id ?? null);
      })
      .catch(() => {});
    get<ShortTest[]>("/teacher/shorttests")
      .then((rows) => {
        if (live) setTests(rows ?? []);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  async function assign(e: React.FormEvent) {
    e.preventDefault();
    if (roomId === null || busy || !chapter.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const st = await post<ShortTest>("/teacher/shorttests", {
        classroom_id: roomId,
        subject,
        chapter: chapter.trim(),
        num_questions: num,
        duration_min: duration,
      });
      setTests((ls) => [st, ...ls]);
      setMsg(t("stAssigned", { n: st.attempts.length }));
    } catch (err) {
      setMsg(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <Card>
        <div className="card-title">{t("stTitle")}</div>
        <QuickAdvanced
          advanced={advanced}
          onToggle={() => setAdvanced((a) => !a)}
        />
        <form onSubmit={assign} className="row-flex gap-2 section-gap-top">
          <Field
            label={t("stChapterLabel")}
            htmlFor="stchap"
            className="field-inline"
          >
            <input
              id="stchap"
              className="input w-min-field"
              value={chapter}
              onChange={(e) => setChapter(e.target.value)}
            />
          </Field>
          <Field label={t("subject")} htmlFor="stsubj" className="field-inline">
            <select
              id="stsubj"
              className="select"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            >
              <option value="science">{t("subjectScience")}</option>
              <option value="math">{t("subjectMath")}</option>
              <option value="bangla">{t("subjectBangla")}</option>
            </select>
          </Field>
          {advanced && (
            <>
              <Field
                label={t("questionCount")}
                htmlFor="stnum"
                className="field-inline"
              >
                <input
                  id="stnum"
                  className="input w-num"
                  type="number"
                  min={1}
                  max={10}
                  value={num}
                  onChange={(e) => setNum(Number(e.target.value) || 1)}
                />
              </Field>
              <Field
                label={t("qpDuration")}
                htmlFor="stdur"
                className="field-inline"
              >
                <input
                  id="stdur"
                  className="input w-num"
                  type="number"
                  min={1}
                  max={60}
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value) || 1)}
                />
              </Field>
            </>
          )}
          <Button
            variant="primary"
            type="submit"
            loading={busy}
            disabled={!chapter.trim()}
          >
            {t("stAssign")}
          </Button>
        </form>
        {msg && <p className="muted">{msg}</p>}
        {tests.length === 0 ? (
          <p className="muted">{t("stEmpty")}</p>
        ) : (
          <ul>
            {tests.slice(0, 5).map((st) => (
              <li key={st.id}>
                {st.chapter} · {st.subject} · {st.questions.length}Q ·{" "}
                {t("stAssigned", { n: st.attempts.length })}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export function LessonPlanFlow() {
  const [advanced, setAdvanced] = useState(false);
  const [chapter, setChapter] = useState("");
  const [subject, setSubject] = useState("science");
  const [minutes, setMinutes] = useState(35);
  const [level, setLevel] = useState("average");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [lp, setLp] = useState<LessonPlan | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [rooms, setRooms] = useState<
    Array<{ id: number; class_level: number }>
  >([]);

  useEffect(() => {
    let live = true;
    get<{ id: number; class_level: number }[]>("/teacher/classrooms")
      .then((rs) => {
        if (live) setRooms(rs ?? []);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    if (busy || !chapter.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const room = rooms[0];
      if (!room) throw new Error("no classroom");
      const plan = await post<LessonPlan>("/teacher/lesson-plans", {
        class_level: room.class_level,
        subject,
        chapter: chapter.trim(),
        minutes,
        level,
      });
      setLp(plan);
      setEdits({});
    } catch (err) {
      setMsg(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="card-title">{t("lpTitle")}</div>
      <QuickAdvanced
        advanced={advanced}
        onToggle={() => setAdvanced((a) => !a)}
      />
      <form onSubmit={generate} className="row-flex gap-2 section-gap-top">
        <Field
          label={t("lpChapterLabel")}
          htmlFor="lpchap"
          className="field-inline"
        >
          <input
            id="lpchap"
            className="input w-min-field"
            value={chapter}
            onChange={(e) => setChapter(e.target.value)}
          />
        </Field>
        <Field label={t("subject")} htmlFor="lpsubj" className="field-inline">
          <select
            id="lpsubj"
            className="select"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          >
            <option value="science">{t("subjectScience")}</option>
            <option value="math">{t("subjectMath")}</option>
            <option value="bangla">{t("subjectBangla")}</option>
          </select>
        </Field>
        {advanced && (
          <>
            <Field
              label={t("lpMinutesLabel")}
              htmlFor="lpmmin"
              className="field-inline"
            >
              <input
                id="lpmmin"
                className="input w-num-lg"
                type="number"
                min={5}
                max={180}
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value) || 5)}
              />
            </Field>
            <Field
              label={t("lpLevelLabel")}
              htmlFor="lplevel"
              className="field-inline"
            >
              <select
                id="lplevel"
                className="select"
                value={level}
                onChange={(e) => setLevel(e.target.value)}
              >
                <option value="beginner">{t("lpLevelBeginner")}</option>
                <option value="average">{t("lpLevelAverage")}</option>
                <option value="advanced">{t("lpLevelAdvanced")}</option>
              </select>
            </Field>
          </>
        )}
        <Button
          variant="primary"
          type="submit"
          loading={busy}
          disabled={!chapter.trim()}
        >
          {t("lpGenerate")}
        </Button>
      </form>
      {msg && <p className="muted">{msg}</p>}
      {lp && (
        <div className="lesson-print">
          <p className="muted">
            {lp.chapter} · {lp.subject} · {lp.class_level} ·{" "}
            {t("stMinutes", { n: lp.minutes })} ·{" "}
            {lp.level === "beginner"
              ? t("lpLevelBeginner")
              : lp.level === "advanced"
                ? t("lpLevelAdvanced")
                : t("lpLevelAverage")}
          </p>
          {Object.entries(lp.sections).map(([key, value]) => (
            <div key={key} className="mb-2">
              <Field
                label={t(
                  (LESSON_SECTION_LABELS[key] ?? "lpTitle") as Parameters<
                    typeof t
                  >[0],
                )}
                htmlFor={`lpsec-${key}`}
              >
                <textarea
                  id={`lpsec-${key}`}
                  className="textarea"
                  value={edits[key] ?? value}
                  onChange={(e) =>
                    setEdits((m) => ({ ...m, [key]: e.target.value }))
                  }
                  rows={3}
                />
              </Field>
            </div>
          ))}
          <button
            type="button"
            className="lp-no-print"
            onClick={() => window.print()}
          >
            {t("lpPrint")}
          </button>
        </div>
      )}
    </Card>
  );
}

export default function CreatePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const active = (params.get("kind") as CreateEntry | null) ?? null;

  return (
    <main className="shell-main">
      <section className="section-head">
        <h1 className="page-title">{t("tNavCreate")}</h1>
      </section>

      <div className="create-grid" role="list" aria-label={t("cGridTitle")}>
        {ENTRIES.map(({ kind, label, sub, icon: Icon }) => (
          <button
            key={kind}
            role="listitem"
            className={`create-tile${active === kind ? " active" : ""}`}
            aria-pressed={active === kind}
            onClick={() => setParams({ kind })}
          >
            <span className="quick-icon" aria-hidden>
              <Icon size={22} />
            </span>
            <span className="create-tile-body">
              <span className="quick-title quick-title-block">
                {t(label as Parameters<typeof t>[0])}
              </span>
              {sub && (
                <span className="quick-sub">
                  {t(sub as Parameters<typeof t>[0])}
                </span>
              )}
            </span>
          </button>
        ))}
      </div>

      {active === "question_paper" && <QuestionPaperFlow />}
      {active === "short_test" && <ShortTestFlow />}
      {active === "lesson_plan" && <LessonPlanFlow />}
      {["worksheet", "answer_key", "homework", "rubric"].includes(
        active ?? "",
      ) && (
        <CreateHub
          initialKind={
            active as "worksheet" | "answer_key" | "homework" | "rubric"
          }
        />
      )}
      {active === null && (
        <Card>
          <p className="muted flush">{t("cGridTitle")}</p>
        </Card>
      )}

      {active === "quiz" && (
        <Card>
          <div className="card-title">{t("cQuizEntry")}</div>
          <p className="muted">{t("cQuizEntryHint")}</p>
          <div className="section-gap-top">
            <Button
              variant="primary"
              onClick={() => navigate("/teacher/assessments?tab=assignments")}
            >
              {t("cOpen")}
            </Button>
          </div>
        </Card>
      )}
    </main>
  );
}
