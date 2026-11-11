import { Paperclip, Send, Square, X } from "lucide-react";
import { Button } from "../../../components/ui";
import { VoiceButton } from "../../../components/VoiceButton";
import { t } from "../../../i18n";
import { MAX_QUESTION_CHARS } from "../../../lib/tutorQuestion";

/** explicit teaching strategies accepted by ChatSendRequest.strategy. */
const STRATEGIES = [
  "simple",
  "example",
  "book_language",
  "steps",
  "analogy",
] as const;
const STRAT_LABELS: Record<
  (typeof STRATEGIES)[number],
  "stratSimple" | "stratExample" | "stratBook" | "stratSteps" | "stratAnalogy"
> = {
  simple: "stratSimple",
  example: "stratExample",
  book_language: "stratBook",
  steps: "stratSteps",
  analogy: "stratAnalogy",
};

const IMAGE_INTENTS = [
  "imgSolve",
  "imgExplain",
  "imgCheck",
  "imgSteps",
] as const;

/**
 * The composer: error line, strategy chips, attachment preview + intent chips,
 * input row and the send/stop control. Extracted from AITutorPage (FE-03);
 * the page owns the input, the attachment and the send logic.
 */
export function TutorComposer({
  error,
  strategy,
  onStrategy,
  image,
  onRemoveImage,
  onSendIntent,
  input,
  onInput,
  onSend,
  sending,
  onStop,
  fileRef,
  onAttach,
  onTranscript,
  showFootNote,
}: {
  error: string | null;
  strategy: string | null;
  onStrategy: (next: string | null) => void;
  image: { mime_type: string; data_base64: string } | null;
  onRemoveImage: () => void;
  onSendIntent: (text: string) => void;
  input: string;
  onInput: (value: string) => void;
  onSend: () => void;
  sending: boolean;
  onStop: () => void;
  fileRef: React.RefObject<HTMLInputElement>;
  onAttach: (file: File | null) => void;
  onTranscript: (text: string) => void;
  showFootNote: boolean;
}) {
  return (
    <>
      {error && (
        <p className="error error-flush" role="alert">
          {error}
        </p>
      )}

      <div
        className="chips strategy-row"
        role="group"
        aria-label={t("strategyTitle")}
      >
        {STRATEGIES.map((s) => (
          <button
            key={s}
            className={`chip${strategy === s ? " active" : ""}`}
            aria-pressed={strategy === s}
            onClick={() => onStrategy(strategy === s ? null : s)}
          >
            {t(STRAT_LABELS[s])}
          </button>
        ))}
      </div>
      {image && (
        <div className="attach-row attach-flow">
          <div className="row-flex">
            <img
              // CodeQL js/xss-through-dom: the mime comes from an API payload,
              // so the data URL is built only over the allowlist the upload
              // contract enforces server-side (png/jpeg/webp) - anything else
              // renders the generic placeholder instead of an attacker URL.
              src={
                ["image/png", "image/jpeg", "image/webp"].includes(
                  image.mime_type,
                )
                  ? `data:${image.mime_type};base64,${image.data_base64}`
                  : ""
              }
              alt=""
              className="attach-preview"
            />
            <button
              className="icon-btn rate-btn"
              aria-label={t("removeImage")}
              onClick={onRemoveImage}
            >
              <X size={14} aria-hidden />
            </button>
          </div>
          {/* image-question path: capture → preview → pick intent. */}
          <div
            className="chips attach-intents"
            role="group"
            aria-label={t("imgPromptTitle")}
          >
            <span className="muted muted-sm attach-intent-label">
              {t("imgPromptTitle")}
            </span>
            {IMAGE_INTENTS.map((key) => (
              <button
                key={key}
                className="chip"
                onClick={() => onSendIntent(t(key))}
              >
                {t(key)}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="chat-input">
        <input
          className="input"
          value={input}
          placeholder={t("askPlaceholder")}
          // Same bound the API declares (FE-FIX-016): the client stops an
          // over-long paste here rather than spending a round-trip to be told.
          maxLength={MAX_QUESTION_CHARS}
          onChange={(e) => onInput(e.target.value)}
          // FE-FIX-013: on an Android IME, Enter is also how a Bangla
          // composition is confirmed — without this guard the half-composed
          // question is sent on the keystroke that was meant to finish typing
          // it. `isComposing` is the platform's own signal for exactly that;
          // it is false for a real Enter, so nothing else changes.
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) onSend();
          }}
          aria-label={t("askPlaceholder")}
        />
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          onChange={(e) => {
            onAttach(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
        <button
          className="icon-btn rate-btn"
          aria-label={t("attachImage")}
          onClick={() => fileRef.current?.click()}
        >
          <Paperclip size={16} aria-hidden />
        </button>
        <VoiceButton onTranscript={onTranscript} />
        {/* UX-007: ONE element for send/stop. Swapping two <Button>s mid-turn
            replaced the DOM node, so a keyboard or switch user's focus fell to
            <body> the moment their Send press started the turn and Stop — the
            only way to cancel it — became unreachable. Same element, toggled
            label, icon, variant and action keeps the focus where it was. */}
        <Button
          variant={sending ? "soft" : "primary"}
          onClick={sending ? onStop : onSend}
          disabled={!sending && !input.trim()}
          aria-label={sending ? t("stopGenerating") : t("send")}
        >
          {sending ? (
            <Square size={18} aria-hidden />
          ) : (
            <Send size={18} aria-hidden />
          )}
        </Button>
      </div>
      {showFootNote && (
        <span className="muted chat-foot-note">{t("continueTutor")}</span>
      )}
    </>
  );
}
