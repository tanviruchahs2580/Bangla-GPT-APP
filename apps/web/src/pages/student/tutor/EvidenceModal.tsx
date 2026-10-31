import { Modal } from "../../../components/ui";
import { t } from "../../../i18n";
import type { SourceRef } from "../../../types";

/** full sanitized textbook evidence behind the source chip. */
export function EvidenceModal({
  source,
  onClose,
}: {
  source: SourceRef;
  onClose: () => void;
}) {
  // This used to reimplement the shared Modal primitive with a weaker
  // contract — no scroll lock, a focusable backdrop OUTSIDE the trap
  // (Shift+Tab could land on it), role=dialog nested inside a
  // role=button backdrop, and the better primitive left dead in tests. The
  // primitive now owns the portal, focus trap, Escape, scroll lock and
  // focus restore; this component supplies only the evidence body.
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
