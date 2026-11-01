import { Search } from "lucide-react";
import { Button, LoadError } from "../../../components/ui";
import { ConversationChip } from "../../../components/ConversationChip";
import { t } from "../../../i18n";
import type { ConversationOut, MessageSearchHit } from "../../../types";

/**
 * Chat history: the in-transcript search row with its hit list, and the
 * conversation chip row with rename/delete. Extracted from AITutorPage (FE-03);
 * the page owns loading, renaming and deletion.
 */
export function TutorHistory({
  query,
  onQuery,
  onSearch,
  hits,
  onOpenHit,
  conversations,
  conversationsError,
  onRetryConversations,
  conversationId,
  renamingId,
  renameValue,
  onRenameStart,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  onOpenConversation,
  onDeleteConversation,
}: {
  query: string;
  onQuery: (value: string) => void;
  onSearch: () => void;
  hits: MessageSearchHit[] | null;
  onOpenHit: (hit: MessageSearchHit) => void;
  conversations: ConversationOut[] | undefined;
  conversationsError: boolean;
  onRetryConversations: () => void;
  conversationId: number | null;
  renamingId: number | null;
  renameValue: string;
  onRenameStart: (conversation: ConversationOut) => void;
  onRenameChange: (value: string) => void;
  onRenameCommit: (id: number) => void;
  onRenameCancel: () => void;
  onOpenConversation: (id: number) => void;
  onDeleteConversation: (id: number) => void;
}) {
  return (
    <>
      <div className="row-flex chat-search-row">
        <input
          className="input chat-search-input"
          value={query}
          placeholder={t("searchHistory")}
          aria-label={t("searchHistory")}
          onChange={(e) => onQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSearch()}
        />
        <Button
          variant="ghost"
          size="sm"
          onClick={onSearch}
          aria-label={t("searchHistory")}
        >
          <Search size={16} aria-hidden />
        </Button>
      </div>
      {hits && (
        <div className="stack chips-gap">
          {hits.length === 0 && <span className="muted">{t("noResults")}</span>}
          {hits.slice(0, 6).map((h) => (
            <button
              key={h.message_id}
              className="btn btn-ghost search-hit-btn"
              onClick={() => onOpenHit(h)}
            >
              <div>
                <div className="row-title">
                  {h.conversation_title ?? `#${h.conversation_id}`}
                </div>
                <div className="row-sub">{h.snippet}</div>
              </div>
            </button>
          ))}
        </div>
      )}

      {/* F-021: a failed history fetch used to remove the chip row, so old
          chats looked deleted rather than unreachable. */}
      {conversationsError && !conversations && (
        <LoadError onRetry={onRetryConversations} />
      )}

      {conversations && conversations.length > 0 && (
        <div className="chips chips-gap">
          {conversations.slice(0, 8).map((c) =>
            renamingId === c.id ? (
              <input
                key={c.id}
                className="input conv-rename-input"
                value={renameValue}
                aria-label={t("rename")}
                onChange={(e) => onRenameChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onRenameCommit(c.id);
                  if (e.key === "Escape") onRenameCancel();
                }}
                onBlur={() => onRenameCommit(c.id)}
              />
            ) : (
              <ConversationChip
                key={c.id}
                title={c.title ?? `#${c.id}`}
                active={conversationId === c.id}
                onOpen={() => onOpenConversation(c.id)}
                onRename={() => onRenameStart(c)}
                onDelete={() => onDeleteConversation(c.id)}
              />
            ),
          )}
        </div>
      )}
    </>
  );
}
