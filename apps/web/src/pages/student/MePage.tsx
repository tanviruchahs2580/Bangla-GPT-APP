import { asText, suggestionSentence } from "../../lib/text";
import { downloadBlob } from "../../lib/download";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Brain,
  Download,
  FileText,
  Flame,
  LogOut,
  Moon,
  ShieldCheck,
  Sun,
  Trash2,
} from "lucide-react";
import {
  clearMyMemory,
  del,
  get,
  getMyMemory,
  getMyPrefs,
  getMyReport,
  patchMyPrefs,
  revokeAllSessions,
  deleteNote,
  getNotes,
} from "../../api";
import ParentInviteCard from "../../components/ParentInviteCard";
import { track } from "../../lib/analytics";
import { formatServerDateTime } from "../../lib/datetime";
import type { ActivitySummary } from "../../types";
import { useAuth } from "../../AuthContext";
import {
  Avatar,
  Badge,
  Button,
  Card,
  LoadError,
  Segmented,
} from "../../components/ui";
import { friendlyError } from "../../errors";
import { getLang, setLang, t, tSubject } from "../../i18n";
import { roleLabel } from "../../lib/roles";
import { getLowData, toggleLowData } from "../../lib/lowData";
import { currentTheme, toggleTheme } from "../../lib/theme";

// The memory panel shows what the tutor has stored — raw backend keys and
// null values are noise for students, so map known keys to labels, localize
// subject values, and drop empty facts entirely.
const MEMORY_FACT_LABEL: Record<string, Parameters<typeof t>[0]> = {
  name: "memFactName",
  class_level: "memFactClass",
  recent_subjects: "memFactRecentSubjects",
  weak_chapters: "memFactWeakChapters",
  explanation_style: "memFactStyle",
};

function memoryFactRows(
  facts: Record<string, unknown>,
): { key: string; value: string }[] {
  const rows: { key: string; value: string }[] = [];
  for (const [k, v] of Object.entries(facts)) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v) && v.length === 0) continue;
    const label = MEMORY_FACT_LABEL[k] ?? k;
    const value = Array.isArray(v)
      ? v.map((item) => tSubject(asText(item))).join(", ")
      : asText(v);
    rows.push({ key: t(label), value });
  }
  return rows;
}

export default function MePage() {
  const { me, signOut } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // F-142: erasure re-authenticates — the confirm card collects the current
  // password and DELETE /users/me carries it in the body.
  const [delPassword, setDelPassword] = useState("");
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [dark, setDark] = useState(currentTheme() === "dark");
  // low-data mode (skip images + short tutor answers)
  const [lowData, setLowDataState] = useState(getLowData());

  // learning preferences + tutor memory + own progress report.
  const isStudent = me?.role === "student";
  const { data: prefs, refetch: refetchPrefs } = useQuery({
    queryKey: ["my-prefs"],
    queryFn: getMyPrefs,
    enabled: isStudent,
  });
  const {
    data: mem,
    isError: memError,
    refetch: refetchMem,
  } = useQuery({
    queryKey: ["my-memory"],
    queryFn: getMyMemory,
    enabled: isStudent,
  });
  const [reportPeriod, setReportPeriod] = useState<"weekly" | "monthly">(
    "weekly",
  );
  // The tutor's bookmark button has always written notes; until now nothing
  // could read them back, so "Saved" was a claim the product could not honour.
  // F-021: a failed fetch must not read as "you have no saved notes".
  const {
    data: notes,
    isError: notesError,
    refetch: refetchNotes,
  } = useQuery({
    queryKey: ["my-notes"],
    queryFn: () => getNotes(),
  });
  const removeNote = async (id: number) => {
    try {
      await deleteNote(id);
      await refetchNotes();
      track("note_deleted");
    } catch {
      /* the list refetch is the source of truth; a failed delete stays visible */
    }
  };
  const {
    data: report,
    isError: reportError,
    refetch: refetchReport,
  } = useQuery({
    queryKey: ["my-report", reportPeriod],
    queryFn: () => getMyReport(reportPeriod),
    enabled: isStudent,
    // Hold the previous period's report on screen while the new one loads.
    // Without this, changing the query key made `data` undefined, the
    // `report &&` guard unmounted the whole card, and the weekly/monthly
    // control the user had just clicked went with it -- the section vanished
    // for the length of the request with no spinner and no way back until it
    // resolved.
    placeholderData: (prev) => prev,
  });
  const [style, setStyle] = useState("standard");
  const [focus, setFocus] = useState("");
  const [memory, setMemory] = useState(true);
  const [prefsBusy, setPrefsBusy] = useState(false);
  const [prefsMsg, setPrefsMsg] = useState<string | null>(null);
  // The same state carries success and failure copy; without this flag the
  // failure was rendered with the success class, green, under the save button.
  const [prefsOk, setPrefsOk] = useState(false);

  useEffect(() => {
    if (!prefs) return;
    // Defensive: a prefs payload without `learning_prefs` (or without the
    // style key) must degrade to the defaults, not crash the effect -- a test
    // mock with a partial payload found this as an uncaught TypeError.
    const learning = prefs.learning_prefs ?? {};
    setStyle(asText(learning.explanation_style ?? "standard"));
    setFocus(asText(learning.subject_focus ?? ""));
    setMemory(prefs.memory_enabled);
  }, [prefs]);

  const savePrefs = async () => {
    setPrefsBusy(true);
    setPrefsMsg(null);
    setPrefsOk(false);
    try {
      const trimmed = focus.trim().slice(0, 60);
      await patchMyPrefs({
        memory_enabled: memory,
        // subject_focus is always sent, as null when the box is empty, because
        // the server merges this dict: sending only the non-empty case left the
        // stored focus in place and the field refilled itself after the refetch.
        learning_prefs: {
          explanation_style: style,
          subject_focus: trimmed || null,
        },
      });
      track("prefs_updated", { style, memory });
      await refetchPrefs();
      await refetchMem();
      setPrefsMsg(t("prefsSaved"));
      setPrefsOk(true);
    } catch {
      setPrefsMsg(t("errorGeneric"));
      setPrefsOk(false);
    } finally {
      setPrefsBusy(false);
    }
  };

  const wipeMemory = async () => {
    try {
      await clearMyMemory();
      track("memory_cleared");
      await refetchMem();
      await refetchPrefs();
    } catch {
      /* keep the facts visible on failure */
    }
  };

  // daily practice heatmap + streak (GitHub-style grid).
  const {
    data: activity,
    isError: activityError,
    refetch: refetchActivity,
  } = useQuery({
    queryKey: ["activity", me?.profile_id],
    queryFn: () => get<ActivitySummary>(`/students/${me?.profile_id}/activity`),
    enabled: me?.role === "student" && me?.profile_id != null,
  });

  // Auth is header-based, so a plain <a href> download would 401; fetch the
  // JSON with the session token and hand the browser a blob URL instead.
  const exportData = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const data = await get<Record<string, unknown>>("/users/me/export");
      downloadBlob(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
        "bangla-gpt-data-export.json",
      );
    } catch (e) {
      setExportError(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setExporting(false);
    }
  };

  const deleteAccount = async () => {
    setBusy(true);
    setError(null);
    try {
      await del("/users/me", { password: delPassword });
      // signOut() wipes storage/offline copies and only then redirects
      // (AuthContext, F-036); navigating here too raced that redirect with a
      // second, hard navigation and could cut the wipe short.
      signOut();
    } catch (e) {
      setError(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
      setBusy(false);
    }
  };

  return (
    <main id="main-content" tabIndex={-1} className="shell-main">
      <section className="section-head">
        <h1>{t("me")}</h1>
      </section>

      <Card>
        <div className="row-flex">
          <Avatar name={me?.name ?? me?.email ?? "?"} size="lg" />
          <div className="row-main">
            <div className="row-title profile-name">
              {me?.name ?? me?.email}
            </div>
            <div className="row-sub">{me?.email}</div>
            <div className="badge-row">
              <Badge>{me ? roleLabel(me.role) : "—"}</Badge>
              {me?.class_level ? (
                <Badge tone="teal">
                  {t("classLabel")} {me.class_level}
                </Badge>
              ) : null}
            </div>
          </div>
          <div className="row-flex">
            <Button variant="danger" size="sm" onClick={signOut}>
              <LogOut size={16} aria-hidden /> {t("logout")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={revokeBusy}
              onClick={() => {
                // S-011: server-side epoch stamp kills every session of the
                // account, then the local sign-out finishes the job here.
                setRevokeBusy(true);
                revokeAllSessions()
                  .then(() => signOut())
                  .catch(() => setRevokeBusy(false));
              }}
            >
              <ShieldCheck size={16} aria-hidden /> {t("signOutEverywhere")}
            </Button>
          </div>
        </div>
      </Card>

      {me?.role === "student" && (activity || activityError) && (
        <Card>
          <div className="card-title">{t("activityTitle")}</div>
          {/* F-021: a failed activity fetch used to remove the whole card, so
              "your streak" simply stopped existing instead of saying so. */}
          {activity ? (
            <>
              <div className="row-flex gap-3">
                <span className="quick-icon">
                  <Flame size={20} aria-hidden />
                </span>
                <div className="row-main">
                  <div className="row-title">
                    {t("streakLabel", { days: activity.streak })}
                  </div>
                  <div className="row-sub">{t("activityHint")}</div>
                </div>
              </div>
              {(() => {
                // FE-11: the per-day data lived only in title tooltips —
                // invisible to keyboards and screen readers. The grid is now
                // a labelled image equivalent: one summary name carries the
                // counts a glance would take from the colors.
                const totals = activity.days.reduce(
                  (acc, d) => {
                    acc.questions += d.questions;
                    acc.quizzes += d.quizzes;
                    if (d.questions + d.quizzes > 0) acc.active += 1;
                    return acc;
                  },
                  { questions: 0, quizzes: 0, active: 0 },
                );
                const gridLabel = t("heatmapSummary", {
                  questions: totals.questions,
                  active: totals.active,
                  days: activity.days.length,
                });
                return (
                  <div
                    className="heatmap"
                    data-testid="activity-heatmap"
                    role="img"
                    aria-label={gridLabel}
                  >
                    <span className="sr-only">{gridLabel}</span>
                    {activity.days.map((d) => {
                      const total = d.questions + d.quizzes;
                      const lvl =
                        total === 0 ? 0 : total <= 2 ? 1 : total <= 5 ? 2 : 3;
                      const title = [
                        d.date,
                        t(
                          d.questions === 1
                            ? "activityQuestion"
                            : "activityQuestions",
                          { n: d.questions },
                        ),
                        t("activityQuizzes", { n: d.quizzes }),
                        t("activityMinutes", { n: d.minutes }),
                      ].join(" · ");
                      return (
                        <span
                          key={d.date}
                          className={`heat-cell lvl-${lvl}`}
                          title={title}
                        />
                      );
                    })}
                  </div>
                );
              })()}
            </>
          ) : (
            <LoadError onRetry={() => void refetchActivity()} />
          )}
        </Card>
      )}

      {(isStudent || (notes ?? []).length > 0 || notesError) && (
        <Card>
          <div className="card-title">{t("savedNotesTitle")}</div>
          {notesError ? (
            /* F-021: "no saved notes" after a failure was a confident, wrong
               statement -- the student's bookmarked answers looked deleted. */
            <LoadError onRetry={() => void refetchNotes()} />
          ) : (notes ?? []).length === 0 ? (
            <p className="muted text-sm m-0">{t("savedNotesEmpty")}</p>
          ) : (
            <ul className="stack notes-list">
              {(notes ?? []).map((n) => (
                <li key={n.id} className="row">
                  <div className="row-main">
                    <div className="row-title">
                      {n.title || n.body.slice(0, 80)}
                    </div>
                    <div className="muted muted-sm">
                      {formatServerDateTime(n.created_at)}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="icon-btn"
                    aria-label={`${t("noteDelete")}: ${n.title || n.body.slice(0, 40)}`}
                    onClick={() => removeNote(n.id)}
                  >
                    <Trash2 size={16} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {me?.role === "student" && <ParentInviteCard />}

      {me?.role === "student" && (
        <Card>
          <div className="card-title">{t("learningStyleTitle")}</div>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="expstyle">{t("explanationStyle")}</label>
              <select
                id="expstyle"
                className="select"
                value={style}
                onChange={(e) => setStyle(e.target.value)}
              >
                <option value="simple">{t("styleSimple")}</option>
                <option value="standard">{t("styleStandard")}</option>
                <option value="detailed">{t("styleDetailed")}</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="subjfocus">{t("subjectFocus")}</label>
              <input
                id="subjfocus"
                className="input"
                value={focus}
                maxLength={60}
                onChange={(e) => setFocus(e.target.value)}
              />
            </div>
          </div>
          {prefsMsg &&
            (prefsOk ? (
              <p className="ok text-sm mt-2">{prefsMsg}</p>
            ) : (
              <p className="error text-sm mt-2" role="alert">
                {prefsMsg}
              </p>
            ))}
          <div className="row-flex gap-2 mt-3">
            <Button
              variant="primary"
              size="sm"
              onClick={() => void savePrefs()}
              disabled={prefsBusy}
            >
              {prefsBusy ? <span className="spinner" aria-hidden /> : null}
              {t("save")}
            </Button>
          </div>
        </Card>
      )}

      {me?.role === "student" && (
        /* AI memory transparency panel — what the tutor knows,
           with the same consent model (toggle off + clear facts). */
        <Card className="card-ai">
          <div className="card-title">{t("aiMemoryPanel")}</div>
          <div className="row-flex spread mt-2">
            <div>
              <div className="setting-label">{t("memoryTitle")}</div>
              <div className="muted text-sm">{t("memoryHint")}</div>
            </div>
            <button
              className="switch"
              role="switch"
              aria-checked={memory}
              aria-label={t("memoryTitle")}
              onClick={() => setMemory((v) => !v)}
            />
          </div>
          <div className="row-flex gap-2 mt-3">
            <Button variant="ghost" size="sm" onClick={() => void wipeMemory()}>
              <Brain size={15} aria-hidden /> {t("clearMemory")}
            </Button>
          </div>
          {/* F-021: a failed facts fetch removed the list silently. */}
          {memError && !mem && (
            <LoadError className="mt-3" onRetry={() => void refetchMem()} />
          )}
          {mem && (
            <div className="mt-3">
              <div className="wrap-list">
                <Badge tone={mem.memory_enabled ? "teal" : "warn"}>
                  {t("memoryFacts")}
                </Badge>
                <span className="muted text-xs">
                  {mem.memory_enabled ? t("on") : t("off")}
                </span>
              </div>
              {memoryFactRows(mem.facts).length === 0 ? (
                <p className="muted text-sm mt-1">{t("noMemoryFacts")}</p>
              ) : (
                <div className="chips mt-1">
                  {memoryFactRows(mem.facts).map(({ key, value }) => (
                    <span key={key} className="chip">
                      {key}: {value}
                    </span>
                  ))}
                </div>
              )}
              {!mem.memory_enabled && (
                <p className="muted text-sm mt-1">
                  {t(mem.on_disable_note_code as Parameters<typeof t>[0]) ||
                    mem.on_disable_note_code}
                </p>
              )}
            </div>
          )}
          {report && (
            /* pattern lines sourced from the existing progress report */
            <div className="mt-3">
              {report.weak_chapters.length > 0 && (
                <div className="wrap-list">
                  <span className="badge badge-warn">
                    {t("aiMemoryPatternWeak")}
                  </span>
                  {report.weak_chapters.slice(0, 3).map((c) => (
                    <span key={c} className="chip">
                      {c}
                    </span>
                  ))}
                </div>
              )}
              {report.strengths.length > 0 && (
                <div className="wrap-list mt-2">
                  <span className="badge badge-teal">
                    {t("aiMemoryPatternStrong")}
                  </span>
                  {report.strengths.slice(0, 3).map((c) => (
                    <span key={c} className="chip">
                      {c}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {me?.role === "student" && reportError && !report && (
        /* F-021: a failed report fetch used to unmount the whole section, so
           the period control and the report vanished with no explanation. */
        <Card>
          <div className="card-title">{t("myReportTitle")}</div>
          <LoadError onRetry={() => void refetchReport()} />
        </Card>
      )}

      {me?.role === "student" && report && (
        <Card>
          <div className="row-flex gap-2">
            <div className="card-title m-0">
              <FileText size={16} aria-hidden /> {t("myReportTitle")}
            </div>
            <Segmented
              className="section-gap-top"
              ariaLabel={t("myReportTitle")}
              value={reportPeriod}
              onChange={(v) => setReportPeriod(v)}
              options={[
                { value: "weekly", label: t("periodWeekly") },
                { value: "monthly", label: t("periodMonthly") },
              ]}
            />
          </div>
          <div className="stat-row mt-3">
            <div>
              <div className="num">{report.quizzes_taken}</div>
              <div className="lbl">{t("reportQuizzesGraded")}</div>
            </div>
            <div>
              <div className="num">
                {report.avg_score_pct == null
                  ? "—"
                  : `${Math.round(report.avg_score_pct)}%`}
              </div>
              <div className="lbl">{t("reportAvg")}</div>
            </div>
            <div>
              <div className="num">{report.chapters_read}</div>
              <div className="lbl">{t("reportChaptersRead")}</div>
            </div>
            <div>
              <div className="num">{report.questions_asked}</div>
              <div className="lbl">{t("reportQuestions")}</div>
            </div>
          </div>
          {report.weak_chapters.length > 0 && (
            <div className="mt-2">
              <span className="muted text-sm">{t("reportWeak")}: </span>
              {report.weak_chapters.map((c) => (
                <Badge key={c} tone="warn">
                  {c}
                </Badge>
              ))}
            </div>
          )}
          {report.strengths.length > 0 && (
            <div className="mt-2">
              <span className="muted text-sm">{t("reportStrengths")}: </span>
              {report.strengths.map((c) => (
                <Badge key={c} tone="ok">
                  {c}
                </Badge>
              ))}
            </div>
          )}
          <p className="muted text-sm mt-2">
            {t("reportSuggestion")}: {suggestionSentence(report)}
          </p>
        </Card>
      )}

      <Card>
        <div className="card-title">{t("settings")}</div>
        <div className="field">
          <label htmlFor="lang">{t("language")}</label>
          <select
            id="lang"
            className="select"
            value={getLang()}
            onChange={(e) => {
              const v = e.target.value as "bn" | "en";
              setLang(v);
              document.documentElement.setAttribute("lang", v);
              // App re-renders the tree in place — no page reload, no state loss.
            }}
          >
            <option value="bn">বাংলা</option>
            <option value="en">English</option>
          </select>
        </div>
        <div className="row-flex spread">
          <div>
            <div className="setting-label">{t("appearance")}</div>
            <div className="muted text-sm">{t("darkMode")}</div>
          </div>
          <button
            className="icon-btn"
            aria-label={t("darkMode")}
            onClick={() => setDark(toggleTheme() === "dark")}
          >
            {dark ? (
              <Sun size={18} aria-hidden />
            ) : (
              <Moon size={18} aria-hidden />
            )}
          </button>
        </div>
        <div className="row-flex spread mt-3">
          <div>
            <div className="setting-label">{t("lowDataTitle")}</div>
            <div className="muted text-sm">{t("lowDataHint")}</div>
          </div>
          <button
            className="switch"
            role="switch"
            aria-checked={lowData}
            aria-label={t("lowDataTitle")}
            onClick={() => setLowDataState(toggleLowData())}
          />
        </div>
      </Card>

      <Card>
        <div className="card-title">{t("account")}</div>
        <div className="stack-sm">
          <Button
            variant="ghost"
            onClick={exportData}
            disabled={exporting}
            className="btn-start"
          >
            {exporting ? (
              <span className="spinner" aria-hidden />
            ) : (
              <Download size={18} aria-hidden />
            )}{" "}
            {t("exportData")}
          </Button>
          {exportError && <p className="error m-0">{exportError}</p>}
          {!confirming ? (
            <Button variant="danger" onClick={() => setConfirming(true)}>
              <Trash2 size={18} aria-hidden /> {t("deleteAccount")}
            </Button>
          ) : (
            <div className="stack">
              <p className="error m-0">{t("deleteWarning")}</p>
              <div className="stack">
                <label className="label" htmlFor="del-password">
                  {t("deleteConfirmPassword")}
                </label>
                <input
                  id="del-password"
                  type="password"
                  className="input"
                  autoComplete="current-password"
                  value={delPassword}
                  onChange={(e) => setDelPassword(e.target.value)}
                />
              </div>
              <div className="row-flex">
                <Button
                  variant="danger"
                  onClick={deleteAccount}
                  disabled={busy || delPassword.length === 0}
                >
                  {t("confirmDelete")}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setConfirming(false);
                    setDelPassword("");
                  }}
                >
                  {t("cancel")}
                </Button>
              </div>
              {error && <p className="error m-0">{error}</p>}
            </div>
          )}
        </div>
      </Card>
    </main>
  );
}
