import { Paperclip, Send, Square, X } from "lucide-react";
import { Button } from "../../../components/ui";
import { VoiceButton } from "../../../components/VoiceButton";
import { t } from "../../../i18n";

/** explicit teaching strategies accepted by ChatSendRequest.strategy. */
export const STRATEGIES = [
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
      {error && <p className="error error-flush">{error}</p>}

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
              src={`data:${image.mime_type};base64,${image.data_base64}`}
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
          onChange={(e) => onInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSend()}
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
        {sending ? (
          <Button
            variant="soft"
            onClick={onStop}
            aria-label={t("stopGenerating")}
          >
            <Square size={18} aria-hidden />
          </Button>
        ) : (
          <Button
            variant="primary"
            onClick={onSend}
            disabled={!input.trim()}
            aria-label={t("send")}
          >
            <Send size={18} aria-hidden />
          </Button>
        )}
      </div>
      {showFootNote && (
        <span className="muted chat-foot-note">{t("continueTutor")}</span>
      )}
    </>
  );
}
