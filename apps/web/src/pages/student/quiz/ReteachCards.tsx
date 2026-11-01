import { Card } from "../../../components/ui";
import { t } from "../../../i18n";
import type { ReteachCard } from "../../../types";

/**
 * F-094 split: the grounded re-teach cards, shared by the result screen and
 * the in-progress screen's first question (KG gap -> textbook excerpt, never
 * AI text).
 */
export function ReteachCards({ cards }: { cards: ReteachCard[] }) {
  if (cards.length === 0) return null;
  return (
    <Card className="reteach-card card-ai">
      <div className="card-title">{t("reteachTitle")}</div>
      <p className="muted muted-sm reteach-hint">{t("reteachHint")}</p>
      <div className="stack">
        {cards.map((c, i) => (
          <div key={i} className="reteach-item">
            <div className="row-title">
              {t("reteachChain", { concept: c.concept, prereq: c.prereq })}
            </div>
            <p className="reteach-excerpt">{c.excerpt}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}
