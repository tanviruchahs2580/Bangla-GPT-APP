import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  BookOpen,
  Bookmark,
  Check,
  Circle,
  FileText,
  Play,
} from "lucide-react";
import { getLearnProgress, getSubjectChapters, getSubjects } from "../../api";
import { track } from "../../lib/analytics";
import type { ChapterSummaryOut, SubjectOut } from "../../types";
import { useAuth } from "../../AuthContext";
import { Card, LoadError } from "../../components/ui";
import { OfflineLibrary } from "../../components/OfflineLibrary";
import { t, tSubject } from "../../i18n";
import { cn } from "../../lib/cn";
import { chapterBadge } from "../../lib/progress";

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
    queryFn: () => {
      if (!activeSubject) throw new Error("no subject selected");
      return getSubjectChapters(activeSubject, selected);
    },
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
        <h1>{t("subjects")}</h1>
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

      {me && (
        <OfflineLibrary
          userId={me.user_id}
          onOpen={(rec) =>
            void navigate(
              `/student/learn/${encodeURIComponent(rec.subject)}/${encodeURIComponent(rec.chapter)}?class=${rec.classLevel}`,
            )
          }
        />
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
                  badgeKind === "done" ? (
                    <Check size={12} />
                  ) : badgeKind === "reading" ? (
                    <Play size={12} />
                  ) : (
                    <Circle size={12} />
                  );
                // The bar reports the progress the reader actually recorded.
                // It used to read `prog ? 45 : 0`, so every in-progress
                // chapter claimed the same invented 45%: a chapter read to 20%
                // and one read to 90% looked identical, and the aria-label
                // announced "45%" as if it were measured. `read_pct` is
                // written by the reader (40 on open, then the scroll
                // position) and is what `chapterBadge` already trusts.
                const pct = prog?.completed ? 100 : (prog?.read_pct ?? 0);
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

export { LearnChapterPage } from "./learn/LearnChapterPage";
