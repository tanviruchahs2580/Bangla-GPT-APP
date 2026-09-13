import { useCallback, useEffect, useRef, useState } from "react";
import { del, downloadTeacherDocumentPdf, get, post } from "../../api";
import type {
  AiJob,
  GeneratedDocument,
  TeacherDocument,
  TeacherWorkload,
} from "../../api";
import { Badge, Button, Card, Segmented } from "../ui";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";
import { track } from "../../lib/analytics";

const KINDS = ["worksheet", "answer_key", "homework", "rubric"] as const;
type Kind = (typeof KINDS)[number];
const PDF_KINDS = new Set(["worksheet", "answer_key", "lesson_plan"]);

// RENO: subject labels come from i18n (were hardcoded Bengali). Evaluated
// at render time so a language switch (in-place remount) is reflected.
const subjectOptions = () => [
  { value: "science", label: t("subjectScience") },
  { value: "mathematics", label: t("subjectMath") },
  { value: "bangla", label: t("subjectBangla") },
];

const KIND_LABEL: Record<
  string,
  | "genWorksheet"
  | "genAnswerKey"
  | "genHomework"
  | "genRubric"
  | "genLessonPlan"
> = {
  worksheet: "genWorksheet",
  answer_key: "genAnswerKey",
  homework: "genHomework",
  rubric: "genRubric",
  lesson_plan: "genLessonPlan",
};
const JOB_LABEL: Record<
  string,
  "jobQueuedS" | "jobGenerating" | "jobValidating" | "jobReady" | "jobFailed"
> = {
  queued: "jobQueuedS",
  generating: "jobGenerating",
  validating: "jobValidating",
  ready: "jobReady",
  failed: "jobFailed",
};

/** Render a generated payload: question lists get a real layout, the rest JSON. */
function PayloadView({ payload }: { payload: Record<string, unknown> }) {
  const qs = payload.questions;
  if (Array.isArray(qs)) {
    return (
      <ol className="gen-questions">
        {qs.map((q, i) => {
          if (q && typeof q === "object") {
            const item = q as Record<string, unknown>;
            return (
              <li key={i}>
                <span>
                  {String(item.question ?? item.text ?? JSON.stringify(item))}
                </span>
                {item.answer != null && (
                  <span className="muted text-sm block">
                    {String(item.answer)}
                  </span>
                )}
              </li>
            );
          }
          return <li key={i}>{String(q)}</li>;
        })}
      </ol>
    );
  }
  return (
    <pre className="data gen-json">{JSON.stringify(payload, null, 2)}</pre>
  );
}

export function CreateHub({
  initialKind,
}: {
  /** WP-DR: when embedded in the Create page grid, the kind is preselected. */
  initialKind?: Kind;
}) {
  const [kind, setKind] = useState<Kind>(initialKind ?? "worksheet");
  const [level, setLevel] = useState(6);
  const [subject, setSubject] = useState("science");
  const [chapter, setChapter] = useState("");
  const [questionsText, setQuestionsText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [result, setResult] = useState<GeneratedDocument | null>(null);

  const [docs, setDocs] = useState<TeacherDocument[]>([]);
  const [docKind, setDocKind] = useState<string | null>(null);
  const [openDoc, setOpenDoc] = useState<number | null>(null);

  const [jobs, setJobs] = useState<AiJob[]>([]);
  const [workload, setWorkload] = useState<TeacherWorkload | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadDocs = useCallback(async () => {
    try {
      const q = docKind ? `?kind=${docKind}&limit=100` : "?limit=100";
      setDocs(
        (await get<TeacherDocument[] | null>(`/teacher/documents${q}`)) ?? [],
      );
    } catch {
      /* library is non-critical chrome */
    }
  }, [docKind]);

  const loadJobs = useCallback(async () => {
    try {
      setJobs((await get<AiJob[] | null>("/teacher/jobs")) ?? []);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void loadDocs();
  }, [loadDocs]);

  // Poll jobs only while at least one is in-flight; stop when settled.
  useEffect(() => {
    const active = jobs.some(
      (j) =>
        j.status === "queued" ||
        j.status === "generating" ||
        j.status === "validating",
    );
    if (active && !pollRef.current) {
      pollRef.current = setInterval(() => void loadJobs(), 2500);
    } else if (!active && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [jobs, loadJobs]);

  useEffect(() => {
    get<TeacherWorkload | null>("/teacher/workload")
      .then((w) => setWorkload(w ?? null))
      .catch(() => {});
  }, []);

  const body = () => {
    const base: Record<string, unknown> = { class_level: level, subject };
    if (chapter.trim()) base.chapter = chapter.trim();
    if (kind === "answer_key") {
      const qs = questionsText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      if (qs.length) base.questions = qs;
    }
    return base;
  };

  const generateNow = async () => {
    setBusy(true);
    setMsg(null);
    setResult(null);
    try {
      const doc = await post<GeneratedDocument | null>(
        `/teacher/generate/${kind}`,
        body(),
      );
      if (doc == null) throw new Error(t("errorGeneric"));
      setResult(doc);
      track("document_generated", { kind, mode: "sync" });
      void loadDocs();
    } catch (e) {
      setMsg(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setBusy(false);
    }
  };

  const queueJob = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await post<AiJob | null>("/teacher/jobs", { kind, payload: body() });
      track("document_generated", { kind, mode: "job" });
      setMsg(t("jobQueuedHint"));
      void loadJobs();
    } catch (e) {
      setMsg(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setBusy(false);
    }
  };

  const removeDoc = async (id: number) => {
    try {
      await del(`/teacher/documents/${id}`);
      setDocs((d) => d.filter((x) => x.id !== id));
      if (openDoc === id) setOpenDoc(null);
    } catch {
      /* ignore */
    }
  };

  return (
    <Card>
      <div className="card-title">{t("createHubTitle")}</div>

      <Segmented
        className="mb-3"
        ariaLabel={t("genKind")}
        value={kind}
        onChange={(k) => setKind(k)}
        options={KINDS.map((k) => ({ value: k, label: t(KIND_LABEL[k]) }))}
      />

      <div className="grid-2">
        <label className="field">
          <span className="lbl">{t("classLevel")}</span>
          <input
            className="input"
            type="number"
            min={1}
            max={12}
            value={level}
            onChange={(e) => setLevel(Number(e.target.value) || 6)}
          />
        </label>
        <label className="field">
          <span className="lbl">{t("subject")}</span>
          <select
            className="input"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          >
            {subjectOptions().map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="lbl">
            {kind === "homework" || kind === "rubric"
              ? t("chapterRequired")
              : t("chapterOptional")}
          </span>
          <input
            className="input"
            value={chapter}
            onChange={(e) => setChapter(e.target.value)}
          />
        </label>
      </div>
      {kind === "answer_key" && (
        <label className="field mt-3">
          <span className="lbl">{t("genQuestionsHint")}</span>
          <textarea
            className="input"
            rows={4}
            value={questionsText}
            onChange={(e) => setQuestionsText(e.target.value)}
          />
        </label>
      )}

      <div className="row-flex gap-2 mt-3">
        {/* Server-side contracts: answer_key needs question lines; homework and
            rubric need a chapter. Keep the buttons quiet until they exist. */}
        <Button
          variant="primary"
          onClick={() => void generateNow()}
          disabled={
            busy ||
            (kind === "answer_key" && !body().questions) ||
            ((kind === "homework" || kind === "rubric") && !chapter.trim())
          }
        >
          {busy ? <span className="spinner" aria-hidden /> : null} {t("genNow")}
        </Button>
        <Button
          variant="soft"
          onClick={() => void queueJob()}
          disabled={
            busy ||
            (kind === "answer_key" && !body().questions) ||
            ((kind === "homework" || kind === "rubric") && !chapter.trim())
          }
        >
          {t("genLater")}
        </Button>
      </div>
      {msg && <p className="muted text-sm">{msg}</p>}

      {result && (
        <div className="card mt-3">
          <div className="card-title">{result.title}</div>
          <PayloadView payload={result.payload} />
          {result.sources.length > 0 && (
            <p className="muted text-sm mt-2">
              {t("genSourcesCount").replace(
                "{n}",
                String(result.sources.length),
              )}
            </p>
          )}
          {PDF_KINDS.has(result.kind) && (
            <Button
              variant="teal"
              size="sm"
              className="mt-2"
              onClick={() => void downloadTeacherDocumentPdf(result)}
            >
              {t("genDownloadPdf")}
            </Button>
          )}
        </div>
      )}

      {jobs.length > 0 && (
        <div className="mt-4">
          <div className="card-title">{t("genJobs")}</div>
          <div className="table-wrap">
            <table className="data">
              <tbody>
                {jobs.slice(0, 8).map((j) => (
                  <tr key={j.id}>
                    <td>
                      {KIND_LABEL[j.kind] ? t(KIND_LABEL[j.kind]) : j.kind}
                    </td>
                    <td>
                      <Badge
                        tone={
                          j.status === "failed"
                            ? "warn"
                            : j.status === "ready"
                              ? "ok"
                              : "teal"
                        }
                      >
                        {t(JOB_LABEL[j.status] ?? "jobQueuedS")}
                      </Badge>
                    </td>
                    <td className="muted">
                      {j.error ??
                        (j.result?.document_id
                          ? `#${j.result.document_id}`
                          : "")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="mt-4">
        <div className="row-flex gap-2">
          <div className="card-title">{t("genLibrary")}</div>
          <button
            className={`chip${docKind === null ? " active" : ""}`}
            onClick={() => setDocKind(null)}
          >
            {t("genAll")}
          </button>
          {[...KINDS, "lesson_plan"].map((k) => (
            <button
              key={k}
              className={`chip${docKind === k ? " active" : ""}`}
              onClick={() => setDocKind(k)}
            >
              {t(KIND_LABEL[k])}
            </button>
          ))}
        </div>
        {docs.length === 0 && (
          <p className="muted text-sm">{t("noDocumentsYet")}</p>
        )}
        <div className="table-wrap">
          {docs.map((d) => (
            <div key={d.id} className="gen-doc-row">
              <button
                className="gen-doc-open"
                onClick={() => setOpenDoc(openDoc === d.id ? null : d.id)}
              >
                <span className="gen-doc-title">{d.title}</span>
                <Badge tone="teal">
                  {KIND_LABEL[d.kind] ? t(KIND_LABEL[d.kind]) : d.kind}
                </Badge>
                <span className="muted text-xs">
                  {d.subject} · {d.class_level}
                </span>
              </button>
              <span className="row-flex gap-1">
                {PDF_KINDS.has(d.kind) && (
                  <button
                    className="small secondary"
                    onClick={() => void downloadTeacherDocumentPdf(d)}
                  >
                    {t("genDownloadPdf")}
                  </button>
                )}
                <button
                  className="small secondary"
                  onClick={() => void removeDoc(d.id)}
                >
                  {t("deleteGeneric")}
                </button>
              </span>
            </div>
          ))}
        </div>
        {openDoc != null && docs.find((d) => d.id === openDoc) && (
          <div className="card mt-2">
            <PayloadView
              payload={docs.find((d) => d.id === openDoc)!.payload}
            />
          </div>
        )}
      </div>

      {workload && (
        <div className="stat-row mt-4" title={workload.methodology}>
          <div>
            <div className="num">{workload.total_minutes_saved}</div>
            <div className="lbl">
              {t("workloadMinutes", { n: workload.total_minutes_saved })}
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
