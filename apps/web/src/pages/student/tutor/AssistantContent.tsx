import { t } from "../../../i18n";
import { SafeMarkdownLazy as SafeMarkdown } from "../../../lib/safeMarkdownLazy";
import { parseStructuredAnswer } from "../../../lib/structuredAnswer";

/** renders the sectioned answer layout when present, plain markdown otherwise. */
export function AssistantContent({ content }: { content: string }) {
  const parsed = parseStructuredAnswer(content);
  if (!parsed.structured) return <SafeMarkdown content={content} />;
  return (
    <div className="structured-answer">
      {parsed.simple && (
        <section>
          <h3 className="section-label">{t("saSimple")}</h3>
          <SafeMarkdown content={parsed.simple} />
        </section>
      )}
      {parsed.example && (
        <section>
          <h3 className="section-label">{t("saExample")}</h3>
          <SafeMarkdown content={parsed.example} />
        </section>
      )}
      {parsed.points.length > 0 && (
        <section>
          <h3 className="section-label">{t("saPoints")}</h3>
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
