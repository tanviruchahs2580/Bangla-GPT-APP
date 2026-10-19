import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  BookOpen,
  Bookmark,
  Download,
  FileText,
  Square,
  Volume2,
} from "lucide-react";
import {
  getChapterContent,
  getLearnProgress,
  getSubjectChapters,
  getSubjects,
  post,
  upsertLearnProgress,
} from "../../api";
import { track } from "../../lib/analytics";
import type {
  AskResponse,
  ChapterSummaryOut,
  QuizResult,
  QuizStarted,
  SubjectOut,
} from "../../types";
import { useAuth } from "../../AuthContext";
import { Card, LoadError } from "../../components/ui";
import { t, tSubject } from "../../i18n";
import { cn } from "../../lib/cn";
import { chapterBadge } from "../../lib/progress";
import {
  TTS_PITCH,
  TTS_RATE,
  clampTtsValue,
  readTtsPrefs,
  resolveBanglaVoice,
  ttsSupport,
} from "../../lib/tts";
import { SafeMarkdownLazy as SafeMarkdown } from "../../lib/safeMarkdownLazy";
import {
  fetchChapterWithOfflineFallback,
  isQuotaExceeded,
  loadChapter,
  saveChapter,
} from "../../lib/offlineStore";
import { getLowData } from "../../lib/lowData";

const SUBJECT_TONE: Record<string, string> = {
  science: "tile-teal",
  mathematics: "tile-warn",
  bangla: "",
};

const EMPTY_SUBJECTS: SubjectOut[] = [];

export function LearnPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<number>(me?.class_level ?? 6);

  const classes = Array.from({ length: 12 }, (_, i) => i + 1);
  const subjectsQuery = useQuery({
    queryKey: ["subjects", selected],
    queryFn: () => getSubjects(selected),
  });
  const [activeSubject, setActiveSubject] = useState<string | null>(null);
  const chaptersQuery = useQuery({
    queryKey: ["chapters", activeSubject, selected],
    queryFn: () => getSubjectChapters(activeSubject!, selected),
    enabled: !!activeSubject,
  });
  // one progress query for the whole class powers both the subject
  // rings and the chapter status icons (all data already returned by the API).
  const allProgressQuery = useQuery({
    queryKey: ["learnProgressAll", selected],
    queryFn: () => getLearnProgress(undefined, selected),
  });
  // A shared constant, not `?? []`: a fresh array identity on every render makes
  // every effect that depends on `subjects` re-run forever.
  const subjects = subjectsQuery.data ?? EMPTY_SUBJECTS;

  // Chapter totals per subject (for the ring denominator), from the same
  // existing chapters endpoint the list view already uses.
  const [totals, setTotals] = useState<Record<string, number>>({});
  useEffect(() => {
    if (subjects.length === 0) return;
    let alive = true;
    void Promise.all(
      subjects.map(async (s: SubjectOut) => {
        try {
          const rows = await getSubjectChapters(s.subject, selected);
          return [s.subject, rows.length] as const;
        } catch {
          return [s.subject, 0] as const;
        }
      }),
    ).then((entries) => {
      if (alive) setTotals(Object.fromEntries(entries));
    });
    return () => {
      alive = false;
    };
  }, [subjects, selected]);

  const progressMap = new Map(
    (allProgressQuery.data ?? []).map((p) => [p.chapter, p]),
  );

  const subjectStats = (subject: string) => {
    const rows = (allProgressQuery.data ?? []).filter(
      (p) => p.subject === subject,
    );
    const done = rows.filter((p) => p.completed).length;
    const total = totals[subject] ?? 0;
    return {
      done,
      total,
      pct: total > 0 ? Math.round((done / total) * 100) : 0,
    };
  };

  return (
    <main id="main-content" tabIndex={-1} className="shell-main">
      <section className="section-head">
        <h2>{t("subjects")}</h2>
      </section>

      <div
        className="chips chips-gap"
        role="group"
        aria-label={t("selectClass")}
      >
        {classes.map((c) => (
          <button
            key={c}
            className={cn("chip", selected === c && "active")}
            onClick={() => {
              setSelected(c);
              setActiveSubject(null);
            }}
          >
            {t("classLabel")} {c}
          </button>
        ))}
      </div>

      {subjectsQuery.isLoading ? (
        <div className="stack">
          <div className="skeleton skeleton-card" />
          <div className="skeleton skeleton-card" />
        </div>
      ) : subjectsQuery.isError ? (
        /* Without this branch a failed fetch fell through to the grid below
           with an empty list, and the page looked like a catalogue with
           nothing in it rather than a request that did not answer. */
        <Card>
          <LoadError onRetry={() => void subjectsQuery.refetch()} />
        </Card>
      ) : (
        <div className="subject-grid">
          {subjects.map((s: SubjectOut) => {
            const stat = subjectStats(s.subject);
            return (
              <button
                key={s.subject}
                className={cn(
                  "subject-card",
                  activeSubject === s.subject && "active",
                )}
                aria-pressed={activeSubject === s.subject}
                onClick={() =>
                  setActiveSubject((cur) =>
                    cur === s.subject ? null : s.subject,
                  )
                }
              >
                <span
                  className={cn("quick-icon", SUBJECT_TONE[s.subject] ?? "")}
                  aria-hidden
                >
                  <BookOpen size={22} />
                </span>
                <div className="subject-name">{tSubject(s.subject)}</div>
                <div className="subject-meta">
                  {t("classLabel")} {s.class_levels.join(", ")}
                </div>
                {stat.total > 0 && (
                  <>
                    <span
                      className="subject-ring"
                      role="img"
                      aria-label={t("chaptersDone", {
                        done: stat.done,
                        total: stat.total,
                      })}
                      style={{ ["--p" as string]: stat.pct }}
                    >
                      <span className="subject-ring-inner">
                        {stat.done}/{stat.total}
                      </span>
                    </span>
                    <span className="subject-progress" aria-hidden />
                  </>
                )}
                {stat.total === 0 && (
                  <span className="subject-progress" aria-hidden />
                )}
              </button>
            );
          })}
        </div>
      )}

      {activeSubject && (
        <>
          <section className="section-head">
            <h2>
              {t("chapters")} · {tSubject(activeSubject)}
            </h2>
          </section>
          <div className="stack">
            {chaptersQuery.isLoading ? (
              <Card>
                <div className="skeleton skeleton-text" />
              </Card>
            ) : chaptersQuery.isError ? (
              /* "no chapters for this subject" was also the message after a
                 500, so a broken request was reported as a missing syllabus. */
              <Card>
                <LoadError onRetry={() => void chaptersQuery.refetch()} />
              </Card>
            ) : (chaptersQuery.data ?? []).length === 0 ? (
              <Card>
                <div className="center muted">{t("noChapters")}</div>
              </Card>
            ) : (
              (chaptersQuery.data ?? []).map((ch: ChapterSummaryOut) => {
                const prog = progressMap.get(ch.chapter);
                const badgeKind = chapterBadge(prog);
                const icon =
                  badgeKind === "done"
                    ? "✓"
                    : badgeKind === "reading"
                      ? "▶"
                      : "○";
                const pct = prog?.completed ? 100 : prog ? 45 : 0;
                return (
                  <Card key={ch.chapter} className="row chapter-card">
                    <span className="quick-icon tile-teal" aria-hidden>
                      <FileText size={20} />
                    </span>
                    <div className="row-main">
                      <div className="row-title">
                        {ch.chapter}{" "}
                        <span
                          className={
                            badgeKind === "done" ? "badge badge-teal" : "badge"
                          }
                          aria-hidden
                        >
                          {icon}
                        </span>{" "}
                        {prog?.bookmarked && (
                          <Bookmark
                            size={14}
                            className="bookmark-inline"
                            aria-label={t("downloaded")}
                          />
                        )}
                      </div>
                      <div className="row-sub">
                        {t("preview")}: {ch.excerpt}
                      </div>
                      {pct > 0 && (
                        <div
                          className="chapter-progress"
                          role="img"
                          aria-label={`${pct}%`}
                        >
                          <span style={{ width: `${pct}%` }} />
                        </div>
                      )}
                    </div>
                    <button
                      className="btn btn-soft btn-sm"
                      onClick={() => {
                        track("chapter_open", {
                          subject: activeSubject,
                          chapter: ch.chapter,
                        });
                        void navigate(
                          `/student/learn/${encodeURIComponent(activeSubject)}/${encodeURIComponent(ch.chapter)}?class=${selected}`,
                        );
                      }}
                    >
                      {t("readConcept")}
                    </button>
                  </Card>
                );
              })
            )}
          </div>
        </>
      )}
    </main>
  );
}

export function LearnChapterPage() {
  const { subject, chapter, searchParams } = useRouteParams();
  const navigate = useNavigate();
  const classLevel = Number(searchParams.get("class")) || undefined;
  // one normalized class number keeps the offline key stable
  const offlineClass = classLevel ?? 6;

  const query = useQuery({
    queryKey: ["chapterContent", subject, chapter, classLevel],
    // network first; a saved offline copy covers network failure.
    queryFn: () =>
      fetchChapterWithOfflineFallback(subject!, chapter!, offlineClass, () =>
        getChapterContent(subject!, chapter!, classLevel),
      ),
    enabled: !!subject && !!chapter,
  });

  const [fontScale, setFontScale] = useState(() => {
    try {
      const v = localStorage.getItem("fontScale");
      return v ? parseFloat(v) : 1;
    } catch {
      return 1;
    }
  });
  const [speaking, setSpeaking] = useState(false);
  // AUD-G-12: reader-controlled speech, persisted per device.
  const [ttsPrefs, setTtsPrefs] = useState(() =>
    readTtsPrefs(
      typeof localStorage !== "undefined" ? localStorage : undefined,
    ),
  );
  const [ttsNotice, setTtsNotice] = useState<string | null>(null);
  const [bookmarked, setBookmarked] = useState(false);
  // AUD-G-07: a rejected bookmark write is rolled back and reported here,
  // next to the control, without dropping the reader out of the chapter.
  const [error, setError] = useState<string | null>(null);
  // unified workspace tabs — পড়া | অনুশীলন | জিজ্ঞাসা (no page exit).
  const [tab, setTab] = useState<"read" | "practice" | "ask">("read");
  // offline-copy availability + download button state
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const progressQuery = useQuery({
    queryKey: ["learnProgressOne", subject, chapter, classLevel],
    queryFn: () => getLearnProgress(subject!, classLevel),
    enabled: !!subject && !!chapter,
  });

  useEffect(() => {
    const p = (progressQuery.data ?? []).find((x) => x.chapter === chapter);
    if (p) setBookmarked(p.bookmarked);
  }, [progressQuery.data, chapter]);

  useEffect(() => {
    if (!subject || !chapter) return;
    let alive = true;
    loadChapter(subject, chapter, offlineClass)
      .then((rec) => {
        if (alive) setSaved(!!rec);
      })
      .catch((err) => {
        // AUD-CD-07: an absent offline copy is normal, but a rejected
        // IndexedDB read is not, and it used to disappear silently.
        console.error("offline chapter copy check failed", err);
      });
    return () => {
      alive = false;
    };
  }, [subject, chapter, offlineClass]);

  useEffect(() => {
    if (subject && chapter && classLevel) {
      try {
        localStorage.setItem(
          "lastChapter",
          JSON.stringify({ subject, chapter, class_level: classLevel }),
        );
        localStorage.setItem("fontScale", String(fontScale));
      } catch {
        /* best-effort: a parse failure must not block startup */
      }
    }
  }, [subject, chapter, classLevel, fontScale]);

  // Mark read progress on view
  useEffect(() => {
    if (!query.data || !subject || !chapter || !classLevel) return;
    const t = setTimeout(() => {
      upsertLearnProgress({
        subject,
        chapter,
        class_level: classLevel,
        read_pct: 40,
      }).catch((err) => {
        // AUD-CD-07: progress writes are best-effort, but a rejected one used
        // to leave no trace anywhere.
        console.error("learn progress write failed", err);
      });
      track("chapter_read", { subject, chapter });
    }, 1500);
    let lastReported = 70;
    const onScroll = () => {
      const pct = Math.min(
        100,
        Math.round(
          (window.scrollY /
            Math.max(1, document.body.scrollHeight - window.innerHeight)) *
            100,
        ),
      );
      if (pct <= 70) return;
      // Throttle. This fired on every scroll event past 70%, which on a
      // touch-scroll of a long chapter is dozens of authenticated POSTs per
      // view -- each one a row in chapter_progress (BUG-006). Report the
      // furthest point reached instead of the instantaneous one.
      if (pct <= lastReported) return;
      lastReported = pct;
      upsertLearnProgress({
        subject,
        chapter,
        class_level: classLevel,
        read_pct: pct,
        completed: pct > 90,
      }).catch((err) => {
        // AUD-CD-07: same as the initial write — throttled, not silent.
        console.error("scroll progress write failed", err);
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      clearTimeout(t);
      window.removeEventListener("scroll", onScroll);
    };
  }, [query.data, subject, chapter, classLevel]);

  const toggleBookmark = async () => {
    if (!subject || !chapter || !classLevel) return;
    const next = !bookmarked;
    setError(null);
    setBookmarked(next);
    try {
      await upsertLearnProgress({
        subject,
        chapter,
        class_level: classLevel,
        bookmarked: next,
      });
    } catch (err) {
      // AUD-G-07: the optimistic flip used to stay on screen after a rejected
      // write, so the reader saw a bookmark the server never stored. Roll it
      // back and report it the way the rest of the page does; the reader is
      // not navigated away by this.
      setBookmarked(!next);
      setError(t("errorGeneric"));
      console.error("bookmark toggle failed", err);
    }
  };

  const speak = async () => {
    // AUD-G-12 / G-26: the engine, the voice and the reader's controls are
    // three separate things. Speech only ever starts from this click handler
    // (no autoplay), and when no Bangla voice is installed the reader is told
    // instead of silently hearing Bangla read by an English voice.
    const engine =
      typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (
      !engine ||
      typeof window.SpeechSynthesisUtterance !== "function" ||
      !content
    )
      return;
    if (speaking) {
      engine.cancel();
      setSpeaking(false);
      setTtsNotice(null);
      return;
    }
    // Awaited, not read once: Chromium's voice list arrives asynchronously,
    // and deciding in that window told readers their device cannot speak
    // Bangla when it can (AUD-G-26).
    const voice = await resolveBanglaVoice();
    try {
      const text = content.sections
        .map((s) => `${s.section} ${s.text}`)
        .join(" ");
      const utter = new window.SpeechSynthesisUtterance(text);
      utter.lang = "bn-BD";
      utter.rate = ttsPrefs.rate;
      utter.pitch = ttsPrefs.pitch;
      if (voice) utter.voice = voice;
      utter.onend = () => setSpeaking(false);
      utter.onerror = () => setSpeaking(false);
      setSpeaking(true);
      setTtsNotice(voice ? null : t("ttsNoBanglaVoice"));
      engine.speak(utter);
    } catch {
      setSpeaking(false);
    }
  };

  const content = query.data?.content;
  const offlineCopy = query.data?.offline === true;
  const ttsEngine = ttsSupport();

  const updateTtsPref = (key: "rate" | "pitch", raw: number) => {
    const bounds = key === "rate" ? TTS_RATE : TTS_PITCH;
    const value = clampTtsValue(raw, bounds);
    setTtsPrefs((prev) => ({ ...prev, [key]: value }));
    try {
      // Device preference, not user data: survives sign-out with theme and
      // language (see USER_STORAGE_KEYS in api.ts).
      localStorage.setItem(
        key === "rate" ? "ttsRate" : "ttsPitch",
        String(value),
      );
    } catch {
      /* private mode: the in-memory value still applies for this session */
    }
  };

  const download = async () => {
    if (!content || !subject || !chapter) return;
    setSaving(true);
    setError(null);
    try {
      await saveChapter(subject, chapter, offlineClass, content);
      setSaved(true);
    } catch (err) {
      // AUD-G-17: a full device used to look exactly like a successful
      // download. Name the failure next to the button that caused it.
      setError(
        isQuotaExceeded(err) ? t("offlineQuotaFull") : t("offlineSaveFailed"),
      );
      console.error("offline chapter save failed", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <main id="main-content" tabIndex={-1} className="shell-main">
      <button
        className="btn btn-ghost btn-sm chips-gap"
        onClick={() => navigate(-1)}
      >
        ← {t("back")}
      </button>
      {query.isLoading ? (
        <Card>
          <div className="skeleton skeleton-text" />
          <div className="skeleton skeleton-text" />
          <div className="skeleton skeleton-card" />
        </Card>
      ) : query.isError ? (
        <Card>
          <div className="center muted" role="alert">
            {t("loadFailed")}{" "}
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => query.refetch()}
            >
              {t("retry")}
            </button>
          </div>
        </Card>
      ) : !content ? (
        <Card>
          <div className="center muted">{t("noChapters")}</div>
        </Card>
      ) : (
        <Card>
          <div className="reader-controls">
            <span className="badge badge-teal">{content.subject}</span>
            <span className="badge">
              {t("classLabel")} {content.class_level}
            </span>
            <button
              key={String(bookmarked)}
              className={`btn btn-sm ${bookmarked ? "btn-teal bookmark-pop" : "btn-ghost"}`}
              onClick={toggleBookmark}
              aria-label={t("bookmark")}
              aria-pressed={bookmarked}
            >
              <Bookmark
                size={14}
                aria-hidden
                fill={bookmarked ? "currentColor" : "none"}
              />{" "}
              {t("bookmark")}
            </button>
            {error && <p className="error">{error}</p>}
            {ttsEngine.supported ? (
              <>
                <button
                  className="btn btn-sm btn-ghost"
                  onClick={() => void speak()}
                  aria-label={t("listen")}
                  aria-pressed={speaking}
                  aria-describedby={ttsNotice ? "tts-notice" : undefined}
                >
                  {speaking ? (
                    <Square size={14} aria-hidden />
                  ) : (
                    <Volume2 size={14} aria-hidden />
                  )}{" "}
                  {speaking ? t("stop") : t("listen")}
                </button>
                <label className="tts-control">
                  <span className="muted muted-sm">{t("ttsRate")}</span>
                  <input
                    type="range"
                    min={TTS_RATE.min}
                    max={TTS_RATE.max}
                    step={TTS_RATE.step}
                    value={ttsPrefs.rate}
                    onChange={(e) =>
                      updateTtsPref("rate", Number(e.target.value))
                    }
                  />
                </label>
                <label className="tts-control">
                  <span className="muted muted-sm">{t("ttsPitch")}</span>
                  <input
                    type="range"
                    min={TTS_PITCH.min}
                    max={TTS_PITCH.max}
                    step={TTS_PITCH.step}
                    value={ttsPrefs.pitch}
                    onChange={(e) =>
                      updateTtsPref("pitch", Number(e.target.value))
                    }
                  />
                </label>
              </>
            ) : (
              // No engine: say so rather than showing a button that does
              // nothing (AUD-G-12).
              <span className="muted muted-sm">{t("ttsUnsupported")}</span>
            )}
            {ttsNotice && (
              <p
                id="tts-notice"
                className="muted muted-sm tts-notice"
                role="status"
              >
                {ttsNotice}
              </p>
            )}
            {offlineCopy && <span className="badge">{t("offlineBadge")}</span>}
            <button
              className={`btn btn-sm ${saved ? "btn-teal" : "btn-ghost"}`}
              onClick={download}
              disabled={saving}
              aria-label={t("downloadChapter")}
            >
              <Download size={14} aria-hidden />{" "}
              {saved ? t("downloaded") : t("downloadChapter")}
            </button>
            <span className="row-flex font-scale-row">
              <span className="muted muted-sm" aria-hidden>
                A
              </span>
              <input
                type="range"
                min={0.8}
                max={1.4}
                step={0.1}
                value={fontScale}
                onChange={(e) => setFontScale(parseFloat(e.target.value))}
                className="font-range"
                aria-label={t("locFontSize")}
              />
              <span className="muted muted-sm" aria-hidden>
                A+
              </span>
            </span>
          </div>

          {/* in-page tabs — read / practice / ask without leaving the chapter */}
          <div
            className="chips workspace-tabs"
            role="tablist"
            aria-label={t("locWorkspace")}
          >
            {(["read", "practice", "ask"] as const).map((k) => (
              <button
                key={k}
                role="tab"
                aria-selected={tab === k}
                className={cn("chip", tab === k && "active")}
                onClick={() => setTab(k)}
              >
                {k === "read"
                  ? t("tabRead")
                  : k === "practice"
                    ? t("tabPractice")
                    : t("tabAsk")}
              </button>
            ))}
          </div>

          {tab === "read" && (
            <>
              <h1 className="card-title reader-title">{content.chapter}</h1>
              <p className="muted">
                <BookOpen size={15} className="reader-book" aria-hidden />{" "}
                {content.book}
              </p>
              <div
                className="md stack reader-md"
                style={{
                  fontSize: `${fontScale}em`,
                }}
              >
                {content.sections.map((s, i) => (
                  <div key={i}>
                    {s.section && <h3>{s.section}</h3>}
                    <SafeMarkdown content={s.text} />
                  </div>
                ))}
              </div>
            </>
          )}
          {tab !== "ask" && (
            /* visible "AI suggestion: continue with X" card. */
            <div className="ai-suggest-card" role="status">
              <span className="ai-suggest-label" aria-hidden>
                <Bookmark size={14} /> {t("aiSuggestion")}
              </span>
              <span className="ai-suggest-text">
                {(progressQuery.data ?? []).find((x) => x.chapter === chapter)
                  ?.completed
                  ? t("nextSuggestionAsk")
                  : t("nextSuggestionPractice")}
              </span>
              <button
                className="btn btn-soft btn-sm"
                onClick={() =>
                  setTab(
                    (progressQuery.data ?? []).find(
                      (x) => x.chapter === chapter,
                    )?.completed
                      ? "ask"
                      : "practice",
                  )
                }
              >
                {(progressQuery.data ?? []).find((x) => x.chapter === chapter)
                  ?.completed
                  ? t("tabAsk")
                  : t("tabPractice")}
              </button>
            </div>
          )}
          {tab === "practice" && (
            <ChapterPractice
              subject={content.subject}
              chapter={content.chapter}
              classLevel={content.class_level}
            />
          )}
          {tab === "ask" && (
            <ChapterAsk
              subject={content.subject}
              chapter={content.chapter}
              classLevel={content.class_level}
            />
          )}
        </Card>
      )}
    </main>
  );
}

function useRouteParams(): {
  subject: string | null;
  chapter: string | null;
  searchParams: URLSearchParams;
} {
  const parts = window.location.pathname.split("/").filter(Boolean);
  // /student/learn/{subject}/{chapter}
  const idx = parts.indexOf("learn");
  const subject = idx >= 0 ? (parts[idx + 1] ?? null) : null;
  const chapter = idx >= 0 ? (parts[idx + 2] ?? null) : null;
  return {
    subject,
    chapter: chapter ? decodeURIComponent(chapter) : null,
    searchParams: new URLSearchParams(window.location.search),
  };
}

/** অনুশীলন tab: mini quiz with the chapter preselected, no page exit. */
function ChapterPractice({
  subject,
  chapter,
  classLevel,
}: {
  subject: string;
  chapter: string;
  classLevel: number;
}) {
  const { me } = useAuth();
  const [started, setStarted] = useState<QuizStarted | null>(null);
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [current, setCurrent] = useState(0);
  const [result, setResult] = useState<QuizResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await post<QuizStarted>("/quizzes", {
        student_id: me?.profile_id,
        class_level: classLevel,
        subject,
        chapter,
        num_questions: 5,
      });
      setStarted(res);
      setAnswers({});
      setCurrent(0);
      setResult(null);
    } catch (e) {
      const detail = (e as { rawDetail?: { message?: string } }).rawDetail;
      setError(
        typeof detail === "object" && detail?.message
          ? detail.message
          : t("errorGeneric"),
      );
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!started) return;
    setBusy(true);
    try {
      const res = await post<QuizResult>(
        `/quizzes/${started.attempt_id}/submit`,
        {
          answers: started.questions.map((_, i) => answers[i] ?? -1),
        },
      );
      setResult(res);
      setStarted(null);
    } catch {
      setError(t("errorGeneric"));
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return (
      <div className="stack">
        <div className="center">
          <div className="stat-value">{Math.round(result.score_pct)}%</div>
          <div className="muted">
            {t("correctOutOf", {
              correct: result.correct,
              total: result.total,
            })}
          </div>
        </div>
        {result.review.map((r, i) => (
          <Card key={i} className="quiz-review-row">
            <div className="row-title">{r.question_text}</div>
            <div className="row-sub">
              {r.is_correct ? "✓" : `✗ — ${r.options[r.correct_index] ?? ""}`}
            </div>
          </Card>
        ))}
        <button className="btn btn-soft" onClick={start} disabled={busy}>
          {t("startQuiz")} ↻
        </button>
      </div>
    );
  }

  if (started) {
    const q = started.questions[current];
    const chosen = answers[current];
    return (
      <div className="stack">
        <div className="row-flex">
          <span className="badge">
            {current + 1}/{started.questions.length}
          </span>
          <span className="muted muted-sm">{chapter}</span>
        </div>
        <div className="row-title quiz-q-title">{q.question_text}</div>
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
          <button
            className="btn btn-ghost btn-sm"
            disabled={current === 0}
            onClick={() => setCurrent((c) => c - 1)}
          >
            ← {t("previousQuestion")}
          </button>
          {current < started.questions.length - 1 ? (
            <button
              className="btn btn-primary btn-sm"
              onClick={() => setCurrent((c) => c + 1)}
            >
              {t("nextQuestion")} →
            </button>
          ) : (
            <button
              className="btn btn-teal btn-sm"
              onClick={submit}
              disabled={busy}
            >
              {t("finishQuiz")}
            </button>
          )}
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    );
  }

  return (
    <div className="stack center">
      <p className="muted">
        {t("practiceThisChapter")} — {chapter}
      </p>
      <button
        className="btn btn-primary"
        onClick={start}
        disabled={busy || !me?.profile_id}
      >
        {t("startQuiz")}
      </button>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

/** জিজ্ঞাসা tab: tutor scoped to this chapter via the chapter context chip. */
function ChapterAsk({
  subject,
  chapter,
  classLevel,
}: {
  subject: string;
  chapter: string;
  classLevel: number;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ask = async () => {
    const q = question.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await post<AskResponse>("/tutor/ask", {
        question: q,
        class_level: classLevel,
        subject,
        chapter,
        low_data: getLowData(),
      });
      setAnswer(res);
      setQuestion("");
    } catch {
      setError(t("errorGeneric"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="row-flex ask-context-row">
        <span className="badge badge-teal">
          {t("contextChip")}: {chapter}
        </span>
      </div>
      <div className="row-flex ask-row">
        <input
          className="input ask-input"
          value={question}
          placeholder={t("askAboutChapter")}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void ask();
          }}
        />
        <button
          className="btn btn-primary"
          onClick={ask}
          disabled={busy || question.trim().length < 3}
        >
          {t("send")}
        </button>
      </div>
      {busy && <p className="muted">{t("thinking")}</p>}
      {error && <p className="error">{error}</p>}
      {answer && (
        <Card className="chapter-card">
          <div className="chips-gap">
            <span className={answer.grounded ? "badge badge-teal" : "badge"}>
              {answer.grounded ? t("supportedBadge") : t("unsupportedBadge")}
            </span>
          </div>
          <SafeMarkdown content={answer.answer} />
          {answer.sources.length > 0 && (
            <p className="muted muted-sm section-gap-top">
              {t("chapter")}: {answer.sources[0].chapter}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
