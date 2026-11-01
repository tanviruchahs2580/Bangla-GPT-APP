import {
  Bookmark,
  Check,
  RefreshCcw,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { Badge } from "../../../components/ui";
import { AiSparkle, BrandMark } from "../../../components/BrandMark";
import { formatServerDate } from "../../../lib/datetime";
import { t } from "../../../i18n";
import type { ChatMessage, SourceRef } from "../../../types";
import { AssistantContent } from "./AssistantContent";

/**
 * The transcript: empty state, day separators, assistant/user bubbles, the
 * per-answer action bar, confidence row, sources and the thumbs/save/regenerate
 * controls. Extracted from AITutorPage (FE-03) without behaviour change; every
 * callback is owned by the page.
 */
export function TutorThread({
  viewportRef,
  messages,
  streaming,
  subject,
  thanks,
  savedId,
  onSuggest,
  onPickImage,
  onResendStrategy,
  onReteach,
  onRegenerate,
  onQuiz,
  onPractice,
  onEvidence,
  onRate,
  onSaveNote,
}: {
  viewportRef: React.RefObject<HTMLDivElement>;
  messages: ChatMessage[];
  streaming: boolean;
  subject: string;
  thanks: number | null;
  savedId: number | null;
  onSuggest: (text: string) => void;
  onPickImage: () => void;
  onResendStrategy: (index: number, key: string) => void;
  onReteach: (index: number) => void;
  onRegenerate: (index: number) => void;
  onQuiz: (subject: string) => void;
  onPractice: () => void;
  onEvidence: (source: SourceRef) => void;
  onRate: (messageId: number, rating: 1 | -1) => void;
  onSaveNote: (message: ChatMessage) => void;
}) {
  return (
    <div ref={viewportRef} className="chat-thread chat-viewport">
      {messages.length === 0 && !streaming && (
        <div className="center empty-state">
          <div className="empty-mark" aria-hidden>
            <BrandMark size={56} />
          </div>
          <div className="empty-title">{t("emptyChatTitle")}</div>
          <p className="muted">{t("emptyChatSub")}</p>
          <div className="suggest-row">
            {[t("suggestTeach"), t("suggestSolve"), t("suggestQuizMe")].map(
              (q) => (
                <button
                  key={q}
                  type="button"
                  className="suggest-chip"
                  onClick={() => onSuggest(q)}
                >
                  {q}
                </button>
              ),
            )}
            <button
              type="button"
              className="suggest-chip suggest-chip-image"
              onClick={onPickImage}
            >
              {t("suggestImage")}
            </button>
          </div>
        </div>
      )}
      {messages.map((m, i) => {
        const prev = messages[i - 1];
        const tight = prev && prev.role === m.role;
        const day = formatServerDate(m.created_at, {
          day: "numeric",
          month: "short",
        });
        const prevDay = formatServerDate(prev?.created_at, {
          day: "numeric",
          month: "short",
        });
        const showDay = day && day !== prevDay;
        return (
          <div
            // The in-flight placeholder bubbles carry id 0, so a bare
            // `m.id || i` keys them by index — which collides with the real
            // message whose id equals that index (every streamed turn warned
            // "two children with the same key" once a thread had enough
            // messages). The two namespaces below never intersect.
            key={m.id ? `m-${m.id}` : `draft-${i}`}
            className={tight ? "chat-group-tight" : undefined}
          >
            {showDay && (
              <div className="chat-day" aria-hidden>
                {day}
              </div>
            )}
            <div className={`bubble ${m.role}`}>
              {m.role === "assistant" && (
                <span className="bubble-id" aria-hidden>
                  <AiSparkle size={14} /> AI
                </span>
              )}
              {m.role === "assistant" ? (
                <AssistantContent content={m.content} />
              ) : (
                m.content
              )}
              {streaming && i === messages.length - 1 && (
                <span className="stream-cursor" aria-hidden />
              )}
            </div>
            {!streaming &&
              m.role === "assistant" &&
              m.grounded &&
              m.id !== 0 && (
                // smart action bar: one obvious row under every answer.
                <div
                  className="chips chips-gap action-bar"
                  role="group"
                  aria-label={t("quickFollowups")}
                >
                  <button
                    className="chip"
                    onClick={() => onResendStrategy(i, "simple")}
                  >
                    {t("chipSimpler")}
                  </button>
                  <button
                    className="chip"
                    onClick={() => onResendStrategy(i, "example")}
                  >
                    {t("chipExample")}
                  </button>
                  <button className="chip" onClick={() => onQuiz(subject)}>
                    {t("chipQuiz")}
                  </button>
                  <button className="chip" onClick={onPractice}>
                    {t("actionPractice")}
                  </button>
                </div>
              )}
            {m.role === "assistant" && m.confidence != null && (
              <div className="confidence-row">
                <Badge tone={m.confidence >= 0.6 ? "ok" : "warn"}>
                  {t("confidenceBadge", {
                    pct: String(Math.round(m.confidence * 100)),
                  })}
                </Badge>
                {/* low-confidence state: distinct, not alarming. */}
                {m.confidence < 0.6 && (
                  <p className="low-conf-hint" role="status">
                    {t("lowConfidenceHint")}
                  </p>
                )}
              </div>
            )}
            {m.role === "assistant" &&
              ((m.sources && m.sources.length > 0) || m.grounded === false) && (
                <div className="sources">
                  {/* Grounding honesty: a server-verdict of ungrounded is
                     the student-visible truth even when the server sends
                     ZERO sources with it — an unverified answer must not
                     look identical to a cited one just because its
                     sources were withheld. */}
                  {m.grounded === false || m.refused_reason ? (
                    <Badge tone="warn">{t("unsupportedBadge")}</Badge>
                  ) : (
                    <Badge tone="teal">
                      <Check size={12} aria-hidden /> {t("supportedBadge")}
                    </Badge>
                  )}
                  {m.sources && m.sources.length > 0 && (
                    <div className="row-flex source-row">
                      {m.sources.map((s: SourceRef, si) => (
                        <button
                          className="source-chip"
                          key={si}
                          onClick={() => onEvidence(s)}
                          aria-label={`${t("evidenceTitle")}: ${s.chapter || s.book}`}
                        >
                          {s.chapter || s.book}
                        </button>
                      ))}
                    </div>
                  )}
                  {m.id !== 0 && (
                    <div className="row-flex rate-row">
                      <button
                        className="icon-btn rate-btn"
                        aria-label={t("rateUp")}
                        onClick={() => onRate(m.id, 1)}
                      >
                        {thanks === m.id ? (
                          <Check size={16} aria-hidden />
                        ) : (
                          <ThumbsUp size={16} aria-hidden />
                        )}
                      </button>
                      <button
                        className="icon-btn rate-btn"
                        aria-label={t("rateDown")}
                        onClick={() => onRate(m.id, -1)}
                      >
                        <ThumbsDown size={16} aria-hidden />
                      </button>
                      {m.grounded && (
                        <button className="chip" onClick={() => onReteach(i)}>
                          {t("reteach")}
                        </button>
                      )}
                      <button
                        className="icon-btn rate-btn"
                        aria-label={t("saveAsNote")}
                        onClick={() => onSaveNote(m)}
                      >
                        {savedId === m.id ? (
                          <Check size={16} aria-hidden />
                        ) : (
                          <Bookmark size={16} aria-hidden />
                        )}
                      </button>
                      {i === messages.length - 1 && (
                        <button
                          className="chip"
                          onClick={() => onRegenerate(i)}
                        >
                          <RefreshCcw size={13} aria-hidden /> {t("regenerate")}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              )}
          </div>
        );
      })}
      {streaming && (
        <div className="bubble assistant">
          <span className="bubble-id" aria-hidden>
            <AiSparkle size={14} /> AI
          </span>
          <span className="typing-dots">
            <span /> <span /> <span />
          </span>
          <span className="stream-cursor" aria-hidden />
          <span className="visually-hidden">{t("thinking")}</span>
        </div>
      )}
    </div>
  );
}
