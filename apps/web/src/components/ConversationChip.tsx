import { Pencil, Trash2 } from "lucide-react";
import { t } from "../i18n";

/**
 * One entry in the conversation list.
 *
 * The open/rename/delete controls are SIBLINGS inside a non-interactive
 * container. They used to be `<span role="button">` elements nested inside the
 * chip's own `<button>`, which axe reports as nested-interactive and which a
 * screen reader announces as a button inside a button -- two controls that
 * look like one and that a keyboard user cannot tell apart. Rename is offered
 * only for the conversation currently open, which is where the pencil belongs.
 */
export function ConversationChip({
  title,
  active,
  onOpen,
  onRename,
  onDelete,
}: {
  title: string;
  active: boolean;
  onOpen: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  return (
    <div className={active ? "chip conv-chip active" : "chip conv-chip"}>
      <button type="button" className="conv-open" onClick={onOpen}>
        {title}
      </button>
      {active && (
        <button
          type="button"
          aria-label={t("rename")}
          className="conv-icon-action"
          onClick={onRename}
        >
          <Pencil size={12} aria-hidden />
        </button>
      )}
      <button
        type="button"
        aria-label={t("deleteChat")}
        className="conv-icon-action"
        onClick={onDelete}
      >
        <Trash2 size={12} aria-hidden />
      </button>
    </div>
  );
}
