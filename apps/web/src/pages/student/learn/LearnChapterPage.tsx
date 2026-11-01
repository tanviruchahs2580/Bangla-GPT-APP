/** The chapter reader: read/practice/ask tabs, read-aloud and offline copy. */
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  BookOpen,
  Bookmark,
  ChevronLeft,
  Download,
  Square,
  Volume2,
} from "lucide-react";
import {
  getChapterContent,
  getLearnProgress,
  upsertLearnProgress,
} from "../../../api";
import { track } from "../../../lib/analytics";
import { useAuth } from "../../../AuthContext";
import { Card } from "../../../components/ui";
import { invalidateStudyCaches } from "../../../lib/invalidate";
import { t } from "../../../i18n";
import { cn } from "../../../lib/cn";
import {
  hasBanglaTtsVoice,
  ttsSupported as ttsAvailable,
} from "../../../lib/progress";
import { SafeMarkdownLazy as SafeMarkdown } from "../../../lib/safeMarkdownLazy";
import {
  fetchChapterWithOfflineFallback,
  loadChapter,
  saveChapter,
} from "../../../lib/offlineStore";
import { toast } from "../../../lib/toast";
import { ChapterAsk } from "./ChapterAsk";
import { ChapterPractice } from "./ChapterPractice";
import { useRouteParams } from "./useRouteParams";

export function LearnChapterPage() {
  const { subject, chapter, searchParams } = useRouteParams();
  const { me } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const classLevel = Number(searchParams.get("class")) || undefined;
  // one normalized class number keeps the offline key stable
  const offlineClass = classLevel ?? 6;
  // Offline copies are user-scoped (PWA-03): a shared device must never serve
  // one student the chapter another downloaded.
  const userId = me?.user_id;

  const query = useQuery({
    queryKey: ["chapterContent", subject, chapter, classLevel],
    // network first; a saved offline copy covers network failure.
    queryFn: () => {
      if (!subject || !chapter || userId == null)
        throw new Error("reader route is not ready");
      return fetchChapterWithOfflineFallback(
        userId,
        subject,
        chapter,
        offlineClass,
        () => getChapterContent(subject, chapter, classLevel),
      );
    },
    // `enabled` gates the query, so the throw above is unreachable in practice.
    enabled: !!subject && !!chapter && userId != null,
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
  const [bnVoice, setBnVoice] = useState<boolean | null>(null);
  const [bookmarked, setBookmarked] = useState(false);
  // unified workspace tabs — পড়া | অনুশীলন | জিজ্ঞাসা (no page exit).
  const [tab, setTab] = useState<"read" | "practice" | "ask">("read");
  // offline-copy availability + download button state
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const progressQuery = useQuery({
    queryKey: ["learnProgressOne", subject, chapter, classLevel],
    queryFn: () => {
      if (!subject) throw new Error("reader route is not ready");
      return getLearnProgress(subject, classLevel);
    },
    enabled: !!subject && !!chapter,
  });

  useEffect(() => {
    const p = (progressQuery.data ?? []).find((x) => x.chapter === chapter);
    if (p) setBookmarked(p.bookmarked);
  }, [progressQuery.data, chapter]);

  useEffect(() => {
    if (!subject || !chapter || userId == null) return;
    let alive = true;
    loadChapter(userId, subject, chapter, offlineClass)
      .then((rec) => {
        if (alive) setSaved(!!rec);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [subject, chapter, offlineClass, userId]);

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
      })
        .then(() => invalidateStudyCaches(queryClient))
        .catch(() => {});
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
      })
        // The write is what the "reading"/"done" badge and the subject ring
        // read; without this the list behind the reader stayed stale.
        .then(() => invalidateStudyCaches(queryClient))
        .catch(() => {});
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      clearTimeout(t);
      window.removeEventListener("scroll", onScroll);
    };
  }, [query.data, subject, chapter, classLevel, queryClient]);

  const toggleBookmark = async () => {
    if (!subject || !chapter || !classLevel) return;
    const next = !bookmarked;
    setBookmarked(next);
    try {
      await upsertLearnProgress({
        subject,
        chapter,
        class_level: classLevel,
        bookmarked: next,
      });
      invalidateStudyCaches(queryClient);
    } catch {
      /* Bookmarking is best-effort: a failed write must not drop the reader
         out of the chapter they are reading. */
    }
  };

  const content = query.data?.content;
  const offlineCopy = query.data?.offline === true;
  const ttsSupported = ttsAvailable();

  // F-108: read-aloud needs an installed Bengali voice. Desktop Chrome and
  // Safari commonly expose speechSynthesis with none, and the button used to
  // speak Bangla text through an English voice. The list also arrives
  // asynchronously (Chrome announces `voiceschanged`), so re-read it.
  useEffect(() => {
    if (!ttsSupported) return;
    const synth = window.speechSynthesis;
    const read = () => setBnVoice(hasBanglaTtsVoice(synth.getVoices()));
    read();
    synth.addEventListener("voiceschanged", read);
    return () => synth.removeEventListener("voiceschanged", read);
  }, [ttsSupported]);

  const speak = () => {
    try {
      if (!("speechSynthesis" in window) || !content || bnVoice !== true)
        return;
      const synth = window.speechSynthesis;
      if (speaking) {
        synth.cancel();
        setSpeaking(false);
        return;
      }
      const text = content.sections
        .map((s) => `${s.section} ${s.text}`)
        .join(" ");
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = "bn-BD";
      const voice = synth
        .getVoices()
        .find((v) => v.lang.toLowerCase().startsWith("bn"));
      if (voice) utter.voice = voice;
      utter.onend = () => setSpeaking(false);
      utter.onerror = () => setSpeaking(false);
      setSpeaking(true);
      synth.speak(utter);
    } catch {
      setSpeaking(false);
    }
  };

  const download = async () => {
    if (!content || !subject || !chapter || userId == null) return;
    setSaving(true);
    try {
      await saveChapter(userId, subject, chapter, offlineClass, content);
      setSaved(true);
    } catch {
      // Previously swallowed: the button simply did not change and the
      // student believed the chapter was downloaded for the journey home.
      // C2 handoff: a dedicated "storage full" key would name the cause
      // (the budget in offlineStore.ts); errorGeneric is the shipped copy.
      toast(t("errorGeneric"));
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
        <ChevronLeft size={16} aria-hidden /> {t("back")}
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
            {ttsSupported && (
              <button
                className="btn btn-sm btn-ghost"
                onClick={speak}
                aria-label={t("listen")}
                aria-pressed={speaking}
                disabled={bnVoice !== true}
                title={bnVoice === false ? t("ttsUnavailable") : undefined}
              >
                {speaking ? (
                  <Square size={14} aria-hidden />
                ) : (
                  <Volume2 size={14} aria-hidden />
                )}{" "}
                {speaking ? t("stop") : t("listen")}
              </button>
            )}
            {offlineCopy && <span className="badge">{t("offlineBadge")}</span>}
            <button
              className={`btn btn-sm ${saved ? "btn-teal" : "btn-ghost"}`}
              onClick={download}
              disabled={saving}
              aria-label={t("downloadChapter")}
              aria-pressed={saved}
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

          {/* in-page tabs — read / practice / ask without leaving the chapter.
              APG tabs model: roving tabindex + arrow keys move selection and
              focus together; each button controls its panel by id. */}
          <div
            className="chips workspace-tabs"
            role="tablist"
            aria-label={t("locWorkspace")}
            tabIndex={-1}
            onKeyDown={(e) => {
              const keys = ["read", "practice", "ask"] as const;
              const at = keys.indexOf(tab);
              let next: (typeof keys)[number] | null = null;
              if (e.key === "ArrowRight" || e.key === "ArrowDown")
                next = keys[(at + 1) % keys.length];
              else if (e.key === "ArrowLeft" || e.key === "ArrowUp")
                next = keys[(at + keys.length - 1) % keys.length];
              else if (e.key === "Home") next = keys[0];
              else if (e.key === "End") next = keys[keys.length - 1];
              if (next === null) return;
              e.preventDefault();
              setTab(next);
              // selection follows focus; the panel host carries the id
              requestAnimationFrame(() =>
                document.getElementById(`workspace-tab-${next}`)?.focus(),
              );
            }}
          >
            {(["read", "practice", "ask"] as const).map((k) => (
              <button
                key={k}
                id={`workspace-tab-${k}`}
                role="tab"
                aria-selected={tab === k}
                aria-controls="workspace-tab-panel"
                tabIndex={tab === k ? 0 : -1}
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

          <div
            id="workspace-tab-panel"
            role="tabpanel"
            tabIndex={-1}
            hidden={false}
          >
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
                      {s.section && <h2>{s.section}</h2>}
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
          </div>
        </Card>
      )}
    </main>
  );
}
