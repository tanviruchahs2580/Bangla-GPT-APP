import { Modal } from "./ui";
import { t } from "../i18n";
import { SafeMarkdownLazy as SafeMarkdown } from "../lib/safeMarkdownLazy";
import { parseStructuredAnswer } from "../lib/structuredAnswer";
import type { SourceRef } from "../types";

/**
 * The tutor answer's presentation pieces, extracted from AITutorPage
 * (file-size ratchet, AUD-CD-02): the streamed bubble's renderer and the
 * evidence dialog behind a citation chip. Behaviour-identical move — same
 * markup, same class names the e2e specs select (`.sources`,
 * `button.source-chip`, `.chat-group-tight` wrappers live in the page), same
 * `role="dialog"` primitives.
 */

/** Full sanitized textbook evidence behind the source chip.
 *
 * AUD-G-09: this used to hand-roll the backdrop, role="dialog", the Tab trap
 * and the focus restore — a second dialog implementation that drifted from
 * `Modal` (which also locks scroll and makes the backdrop keyboard-
 * dismissible). It now renders the shared primitive and keeps only its own
 * content.
 */
export function EvidenceModal({
  source,
  onClose,
}: {
  source: SourceRef;
  onClose: () => void;
}) {
  const path = [source.book, source.chapter, source.section]
    .filter(Boolean)
    .join(" › ");
  return (
    <Modal open onClose={onClose} title={t("evidenceTitle")}>
      <p className="muted evidence-path">
        {path}
        {source.page != null ? ` · ${t("page")} ${source.page}` : ""}
      </p>
      <blockquote className="evidence-quote">
        {source.excerpt ?? source.chapter}
      </blockquote>
    </Modal>
  );
}

/** Renders the sectioned answer layout when present, plain markdown otherwise. */
export function AssistantContent({ content }: { content: string }) {
  const parsed = parseStructuredAnswer(content);
  if (!parsed.structured) return <SafeMarkdown content={content} />;
  return (
    <div className="structured-answer">
      {parsed.simple && (
        <section>
          <h4 className="section-label">{t("saSimple")}</h4>
          <SafeMarkdown content={parsed.simple} />
        </section>
      )}
      {parsed.example && (
        <section>
          <h4 className="section-label">{t("saExample")}</h4>
          <SafeMarkdown content={parsed.example} />
        </section>
      )}
      {parsed.points.length > 0 && (
        <section>
          <h4 className="section-label">{t("saPoints")}</h4>
          <ul>
            {parsed.points.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </section>
      )}
      {parsed.check && (
        <section className="check-question">
          <SafeMarkdown content={`${t("saCheck")} ${parsed.check}`.trim()} />
        </section>
      )}
    </div>
  );
}
