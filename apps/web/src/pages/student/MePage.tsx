import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Brain,
  Download,
  FileText,
  Flame,
  KeyRound,
  LogOut,
  Moon,
  Sun,
  Trash2,
} from "lucide-react";
import {
  clearMyMemory,
  del,
  generateInviteCode,
  get,
  getMyMemory,
  getMyPrefs,
  getMyReport,
  patchMyPrefs,
} from "../../api";
import { track } from "../../lib/analytics";
import type { ActivitySummary } from "../../types";
import { useAuth } from "../../AuthContext";
import { Avatar, Badge, Button, Card, Segmented } from "../../components/ui";
import { friendlyError } from "../../errors";
import { getLang, setLang, t } from "../../i18n";
import { getLowData, toggleLowData } from "../../lib/lowData";
import { currentTheme, toggleTheme } from "../../lib/theme";

// RENO: roles come from the API in English; display them localized.
const ROLE_LABEL: Record<string, Parameters<typeof t>[0]> = {
  student: "roleStudent",
  teacher: "roleTeacher",
  parent: "roleParent",
  admin: "roleAdmin",
  school_admin: "roleSchoolAdmin",
};

export default function MePage() {
  const { me, signOut } = useAuth();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState<{
    code: string;
    expires_in_minutes: number;
  } | null>(null);
  const [inviteBusy, setInviteBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [dark, setDark] = useState(currentTheme() === "dark");
  // S1.13: low-data mode (skip images + short tutor answers)
  const [lowData, setLowDataState] = useState(getLowData());

  // Wave 2: learning preferences + tutor memory + own progress report.
  const isStudent = me?.role === "student";
  const { data: prefs, refetch: refetchPrefs } = useQuery({
    queryKey: ["my-prefs"],
    queryFn: getMyPrefs,
    enabled: isStudent,
  });
  const { data: mem, refetch: refetchMem } = useQuery({
    queryKey: ["my-memory"],
    queryFn: getMyMemory,
    enabled: isStudent,
  });
  const [reportPeriod, setReportPeriod] = useState<"weekly" | "monthly">(
    "weekly",
  );
  const { data: report } = useQuery({
    queryKey: ["my-report", reportPeriod],
    queryFn: () => getMyReport(reportPeriod),
    enabled: isStudent,
  });
  const [style, setStyle] = useState("standard");
  const [focus, setFocus] = useState("");
  const [memory, setMemory] = useState(true);
  const [prefsBusy, setPrefsBusy] = useState(false);
  const [prefsMsg, setPrefsMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!prefs) return;
    setStyle(String(prefs.learning_prefs.explanation_style ?? "standard"));
    setFocus(String(prefs.learning_prefs.subject_focus ?? ""));
    setMemory(prefs.memory_enabled);
  }, [prefs]);

  const savePrefs = async () => {
    setPrefsBusy(true);
    setPrefsMsg(null);
    try {
      const lp: Record<string, unknown> = { explanation_style: style };
      if (focus.trim()) lp.subject_focus = focus.trim().slice(0, 60);
      await patchMyPrefs({ memory_enabled: memory, learning_prefs: lp });
      track("prefs_updated", { style, memory });
      await refetchPrefs();
      await refetchMem();
      setPrefsMsg(t("prefsSaved"));
    } catch {
      setPrefsMsg(t("errorGeneric"));
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

  // S1.9: daily practice heatmap + streak (GitHub-style grid).
  const { data: activity } = useQuery({
    queryKey: ["activity", me?.profile_id],
    queryFn: () => get<ActivitySummary>(`/students/${me?.profile_id}/activity`),
    enabled: me?.role === "student" && me?.profile_id != null,
  });

  const createInvite = async () => {
    setInviteBusy(true);
    setInviteError(null);
    try {
      const inv = await generateInviteCode();
      setInvite(inv);
      track("parent_invite_generated");
    } catch (e) {
      setInviteError(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
    } finally {
      setInviteBusy(false);
    }
  };

  // Auth is header-based, so a plain <a href> download would 401; fetch the
  // JSON with the session token and hand the browser a blob URL instead.
  const exportData = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const data = await get<Record<string, unknown>>("/users/me/export");
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = "bangla-gpt-data-export.json";
      a.click();
      URL.revokeObjectURL(url);
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
      await del("/users/me");
      signOut();
      navigate("/login");
    } catch (e) {
      setError(
        friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
          t("errorGeneric"),
      );
      setBusy(false);
    }
  };

  return (
    <main className="shell-main">
      <section className="section-head">
        <h2>{t("me")}</h2>
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
              <Badge>
                {me
                  ? ROLE_LABEL[me.role]
                    ? t(ROLE_LABEL[me.role])
                    : me.role
                  : "—"}
              </Badge>
              {me?.class_level ? (
                <Badge tone="teal">
                  {t("classLabel")} {me.class_level}
                </Badge>
              ) : null}
            </div>
          </div>
          <Button variant="danger" size="sm" onClick={signOut}>
            <LogOut size={16} aria-hidden /> {t("logout")}
          </Button>
        </div>
      </Card>

      {me?.role === "student" && activity && (
        <Card>
          <div className="card-title">{t("activityTitle")}</div>
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
          <div
            className="heatmap"
            data-testid="activity-heatmap"
            aria-label={t("streakLabel", { days: activity.streak })}
          >
            {activity.days.map((d) => {
              const total = d.questions + d.quizzes;
              const lvl = total === 0 ? 0 : total <= 2 ? 1 : total <= 5 ? 2 : 3;
              const title = [
                d.date,
                t("activityQuestions", { n: d.questions }),
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
        </Card>
      )}

      {me?.role === "student" && (
        <Card>
          <div className="card-title">{t("parentInviteTitle")}</div>
          <p className="muted text-sm m-0">{t("parentInviteHint")}</p>
          {invite ? (
            <div className="stack">
              <div className="row-flex gap-2">
                <KeyRound size={18} aria-hidden />
                <strong className="invite-code">{invite.code}</strong>
              </div>
              <p className="muted text-sm m-0">
                {t("parentInviteExpires", {
                  minutes: invite.expires_in_minutes,
                })}
              </p>
            </div>
          ) : (
            <Button variant="teal" onClick={createInvite} disabled={inviteBusy}>
              {inviteBusy ? (
                <span className="spinner" aria-hidden />
              ) : (
                <KeyRound size={16} aria-hidden />
              )}
              {t("parentInviteGenerate")}
            </Button>
          )}
          {inviteError && <p className="error m-0">{inviteError}</p>}
        </Card>
      )}

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
          {prefsMsg && <p className="ok text-sm mt-2">{prefsMsg}</p>}
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
        /* WP-DR: AI memory transparency panel — what the tutor knows,
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
              {Object.keys(mem.facts).length === 0 ? (
                <p className="muted text-sm mt-1">{t("noMemoryFacts")}</p>
              ) : (
                <div className="chips mt-1">
                  {Object.entries(mem.facts).map(([k, v]) => (
                    <span key={k} className="chip">
                      {k}: {String(v)}
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
            {t("reportSuggestion")}:{" "}
            {t(report.suggestion_code as Parameters<typeof t>[0]) ||
              report.suggestion_code}
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
              // RENO: LangRoot remounts the tree in place — no page reload.
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
              <div className="row-flex">
                <Button
                  variant="danger"
                  onClick={deleteAccount}
                  disabled={busy}
                >
                  {t("confirmDelete")}
                </Button>
                <Button variant="ghost" onClick={() => setConfirming(false)}>
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
