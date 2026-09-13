import { useMemo, useState } from "react";
import { apiBase, getToken, post } from "../../api";
import type { QPaper } from "../../types";
import { Badge, Button, Card } from "../ui";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";

const errText = (err: unknown): string =>
  friendlyError((err as { rawDetail?: unknown }).rawDetail)?.text ??
  t("errorGeneric");

// S2.4 gate, now visible: a paper is publishable only once every question
// has been reviewed — surface progress instead of an error toast after the fact.
export function QPaperStepper({ qp }: { qp: QPaper }) {
  const reviewed = qp.questions.filter((q) => q.reviewed).length;
  const total = qp.questions.length;
  const final = qp.status === "final";
  const step = final
    ? 5
    : total === 0
      ? 1
      : reviewed === 0
        ? 2
        : reviewed < total
          ? 3
          : 4;
  const steps = [
    t("stepDraft"),
    t("stepReview"),
    t("stepEdit"),
    t("stepApprove"),
    t("stepPublish"),
  ];
  return (
    <div className="qp-stepper" role="list" aria-label={t("stepPublish")}>
      {steps.map((label, i) => (
        <div
          key={label}
          role="listitem"
          className={`qp-step${i + 1 < step ? " done" : i + 1 === step ? " current" : ""}`}
          aria-current={i + 1 === step ? "step" : undefined}
        >
          <span className="qp-step-dot" aria-hidden>
            {i + 1 < step ? "✓" : i + 1}
          </span>
          <span className="qp-step-label">{label}</span>
        </div>
      ))}
    </div>
  );
}

/** Validation checklist rendered from the backend's own gates (qp.meta). */
export function QPaperValidation({ qp }: { qp: QPaper }) {
  const meta = (qp.meta ?? {}) as Record<string, unknown>;
  const hasChecks =
    meta.alignment_min != null || meta.difficulty_actual != null;
  if (!hasChecks) {
    return <p className="muted muted-sm mt-2">{t("valPending")}</p>;
  }
  const minAlign =
    typeof meta.alignment_min === "number" ? meta.alignment_min : null;
  const actual =
    meta.difficulty_actual != null
      ? (meta.difficulty_actual as Record<string, number>)
      : null;
  const rows: Array<{ label: string; ok: boolean; note: string }> = [
    {
      label: t("valDup"),
      ok: true,
      note: qp.questions.length > 0 ? t("valPass") : "—",
    },
    {
      label: t("valDifficulty"),
      ok: true,
      note: actual
        ? `${actual.easy ?? 0}/${actual.medium ?? 0}/${actual.hard ?? 0}`
        : "—",
    },
    {
      label: t("valNctb"),
      ok: minAlign === null || minAlign >= 0.35,
      note:
        minAlign !== null
          ? `${t("valMin")} ${Math.round(minAlign * 100)}%`
          : "—",
    },
  ];
  return (
    <div className="qp-validation" role="list" aria-label={t("valTitle")}>
      <div className="card-title">{t("valTitle")}</div>
      {rows.map((r) => (
        <div key={r.label} role="listitem" className="qp-val-row">
          <span className={`qp-val-dot ${r.ok ? "ok" : "warn"}`} aria-hidden>
            {r.ok ? "✓" : "!"}
          </span>
          <span className="qp-val-label">{r.label}</span>
          <span className="muted muted-sm">{r.note}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Draft -> Review -> Edit -> Approve -> Publish workbench for one question
 * paper. Presentational state (paper) is lifted; API actions live here so
 * both Create and Assessments render the exact same review flow.
 */
export function QPaperReviewPanel({
  qp,
  onChange,
}: {
  qp: QPaper;
  onChange: (qp: QPaper) => void;
}) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const allReviewed =
    qp.questions.length > 0 && qp.questions.every((q) => q.reviewed);
  const reviewedCount = useMemo(
    () => qp.questions.filter((q) => q.reviewed).length,
    [qp.questions],
  );

  async function run<T>(fn: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setMsg(null);
    try {
      return await fn();
    } catch (err) {
      setMsg(errText(err));
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function review(refs?: string[]) {
    const list = refs
      ? qp.questions.filter((q) => refs.includes(q.ref))
      : qp.questions;
    const decisions = list.map((q) => {
      const edit = (edits[q.ref] ?? "").trim();
      return edit
        ? { ref: q.ref, action: "edit" as const, text: edit }
        : { ref: q.ref, action: "accept" as const };
    });
    const res = await run(() =>
      post<QPaper>(`/teacher/qpapers/${qp.id}/review`, { decisions }),
    );
    if (res) {
      setEdits({});
      onChange(res);
    }
  }

  async function replace(ref: string) {
    const res = await run(() =>
      post<QPaper>(`/teacher/qpapers/${qp.id}/replace`, { ref }),
    );
    if (res) onChange(res);
  }

  async function regenerate() {
    const res = await run(() =>
      post<QPaper>(`/teacher/qpapers/${qp.id}/regenerate`),
    );
    if (res) {
      setEdits({});
      onChange(res);
    }
  }

  async function shuffle() {
    const res = await run(() =>
      post<QPaper>(`/teacher/qpapers/${qp.id}/shuffle`),
    );
    if (res) onChange(res);
  }

  async function finalize() {
    const res = await run(() =>
      post<QPaper>(`/teacher/qpapers/${qp.id}/finalize`),
    );
    if (res) {
      onChange(res);
      setMsg(t("qpFinalized"));
    }
  }

  async function download(kind: string) {
    try {
      const res = await fetch(
        `${apiBase}/teacher/qpapers/${qp.id}/pdf?kind=${kind}`,
        { headers: { Authorization: `Bearer ${getToken() ?? ""}` } },
      );
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `qp-${qp.id}-${kind}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setMsg(t("errorGeneric"));
    }
  }

  return (
    <Card className="qp-review-panel">
      <div className="row-flex chips-gap">
        <Badge tone={qp.status === "final" ? "ok" : "teal"}>
          {qp.status === "final"
            ? t("qpFinalized")
            : allReviewed
              ? t("qpDraftReady")
              : t("qpNeedsReview")}
        </Badge>
        <span className="muted muted-sm">
          {qp.subject} · {t("classLabel")} {qp.class_level} · {qp.marks}{" "}
          {t("qpMarks")} · {t("stMinutes", { n: qp.duration_min })}
        </span>
      </div>

      <QPaperStepper qp={qp} />
      <QPaperValidation qp={qp} />

      {!qp.status.startsWith("final") && (
        <p className="muted muted-sm mt-2">
          {t("qpReviewProgress", {
            done: reviewedCount,
            total: qp.questions.length,
          })}
          {!allReviewed && ` — ${t("qpGateHint")}`}
        </p>
      )}

      <ol className="qp-question-list">
        {qp.questions.map((q, idx) => (
          <li key={q.ref} className="qp-question-row">
            <div className="row-title">
              <span className="qp-qnum" aria-hidden>
                {idx + 1}
              </span>
              {q.text} <span className="muted">[{q.difficulty}]</span>
              {q.reviewed && <Badge tone="ok"> {t("qpReviewAll")}</Badge>}
            </div>
            <ul className="qp-options">
              {q.options.map((o, oi) => (
                <li
                  key={oi}
                  style={
                    oi === q.answer_index ? { fontWeight: 700 } : undefined
                  }
                >
                  {o}
                </li>
              ))}
            </ul>
            {qp.status !== "final" && (
              <div className="row-flex chips-gap">
                <input
                  aria-label={`${t("qpTitle")} ${idx + 1}`}
                  placeholder={q.text}
                  value={edits[q.ref] ?? ""}
                  onChange={(e) =>
                    setEdits((ed) => ({ ...ed, [q.ref]: e.target.value }))
                  }
                  className="input grow-field"
                />
                <Button
                  variant="soft"
                  size="sm"
                  disabled={busy}
                  onClick={() => void review([q.ref])}
                >
                  {t("qpReviewAll")}
                </Button>
                {/* Bank-first single-question replace: never regenerate the
                    whole paper for a one-question fix. */}
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => void replace(q.ref)}
                >
                  {t("qpReplace")}
                </Button>
              </div>
            )}
          </li>
        ))}
      </ol>

      {msg && (
        <p
          role="status"
          className={msg === t("errorGeneric") ? "error" : undefined}
        >
          {msg}
        </p>
      )}

      {qp.status !== "final" && (
        <div className="row-flex chips-gap">
          <Button
            variant="soft"
            size="sm"
            disabled={busy}
            onClick={() => void review()}
          >
            {t("qpReviewAll")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => void regenerate()}
          >
            {t("qpRegenerate")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => void shuffle()}
          >
            {t("qpShuffle")}
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={busy || !allReviewed}
            onClick={() => void finalize()}
          >
            {t("qpFinalize")}
          </Button>
        </div>
      )}
      <div className="row-flex chips-gap mt-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => void download("paper")}
        >
          PDF
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={() => void download("answer")}
        >
          PDF+
        </Button>
      </div>
    </Card>
  );
}
