import { asText } from "../../lib/text";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, MessageSquarePlus } from "lucide-react";
import { createNote, del, get, patch, post, postStream } from "../../api";
import type {
  ChatDoneEvent,
  ChatMessage,
  ConversationOut,
  MessageSearchHit,
  SourceRef,
} from "../../types";
import { useAuth } from "../../AuthContext";
import { Button, Card } from "../../components/ui";
import { friendlyError } from "../../errors";
import { t } from "../../i18n";
import { getLowData } from "../../lib/lowData";
import { toast } from "../../lib/toast";
import { track } from "../../lib/analytics";
import { explainMessage, type QuizExplainPayload } from "../../lib/quizExplain";
import { EvidenceModal } from "./tutor/EvidenceModal";
import { TutorComposer } from "./tutor/TutorComposer";
import { TutorHistory } from "./tutor/TutorHistory";
import { TutorThread } from "./tutor/TutorThread";

// labels from i18n, evaluated per render (lang switch remounts).
const subjectOptions = () => [
  { value: "science", label: t("subjectScience") },
  { value: "mathematics", label: t("subjectMath") },
  { value: "bangla", label: t("subjectBangla") },
];

// Attachment contract. The API re-validates both server-side (422
// image_invalid); these bounds must stay in step with docs/API.md.
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
const MAX_IMAGE_BYTES = 1_500_000;

export default function AITutorPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [subject, setSubject] = useState("science");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  // A whole turn is in flight (conversation POST + answer stream). Distinct
  // from `streaming`, which is only true once tokens can arrive — but it must
  // cover the POST too, so Stop can abort the whole turn (F-012).
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Screen readers get ONE polite announcement per completed answer instead
  // of a per-token stream from the transcript (F-016/F-064).
  const [announcement, setAnnouncement] = useState("");
  const [thanks, setThanks] = useState<number | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null);
  // explicit explanation strategy + image attachment.
  const [strategy, setStrategy] = useState<string | null>(null);
  const [image, setImage] = useState<{
    mime_type: string;
    data_base64: string;
  } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  // source → evidence modal.
  const [evidence, setEvidence] = useState<SourceRef | null>(null);
  // history search + rename/delete.
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<MessageSearchHit[] | null>(null);
  const [renamingId, setRenamingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const viewportRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Token batching (audit): every SSE token used to call setMessages with
  // the whole accumulated answer, which re-parsed the full markdown +
  // KaTeX document per token — quadratic main-thread work on exactly the
  // low-end Android devices this app targets. Tokens now accumulate
  // immediately (acc.text stays exact) and the visible bubble refreshes at
  // most every 80 ms; the final merge still writes acc.text verbatim.
  const flushTimerRef = useRef<number | null>(null);
  const pendingTextRef = useRef<string | null>(null);

  const applyStreamedText = useCallback((text: string) => {
    setMessages((m) => {
      const copy = [...m];
      const last = copy[copy.length - 1];
      if (last && last.role === "assistant") {
        // Replace the object instead of mutating it: the previous state
        // array still references `last`, and any future React.memo or
        // memoized consumer would stop seeing updates.
        copy[copy.length - 1] = { ...last, content: text };
      } else {
        copy.push({
          id: 0,
          role: "assistant",
          content: text,
          grounded: null,
          sources: [],
        });
      }
      return copy;
    });
  }, []);

  const flushTokens = useCallback(() => {
    if (flushTimerRef.current !== null) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    const text = pendingTextRef.current;
    pendingTextRef.current = null;
    if (text !== null) applyStreamedText(text);
  }, [applyStreamedText]);

  const scheduleTokenFlush = useCallback(
    (text: string) => {
      pendingTextRef.current = text;
      if (flushTimerRef.current !== null) return;
      flushTimerRef.current = window.setTimeout(() => {
        flushTimerRef.current = null;
        const pending = pendingTextRef.current;
        pendingTextRef.current = null;
        if (pending !== null) applyStreamedText(pending);
      }, 80);
    },
    [applyStreamedText],
  );
  // Synchronous send guard (F-012). State (`streaming`) is only updated after
  // renders, so it cannot gate a second send fired while the conversation
  // POST is still in flight; a ref can.
  const sendingRef = useRef(false);

  const {
    data: conversations,
    isError: conversationsError,
    refetch: refetchConvs,
  } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => get<ConversationOut[]>("/tutor/conversations"),
  });

  // Cancel an in-flight SSE stream when the student leaves the page, and
  // drop any scheduled token flush with it.
  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    },
    [],
  );

  useEffect(() => {
    viewportRef.current?.scrollTo({
      top: viewportRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, streaming]);

  const loadConversation = useCallback(async (id: number) => {
    setConversationId(id);
    setMessages([]);
    setError(null);
    try {
      const msgs = await get<ChatMessage[]>(
        `/tutor/conversations/${id}/messages`,
      );
      setMessages(msgs);
    } catch {
      setError(t("loadFailed"));
    }
  }, []);

  const newChat = useCallback(async () => {
    try {
      const res = await post<ConversationOut>("/tutor/conversations", {});
      await refetchConvs();
      await loadConversation(res.id);
    } catch {
      setError(t("newChatFailed"));
    }
  }, [loadConversation, refetchConvs]);

  const send = useCallback(
    async (
      preset?: string,
      opts?: { reteach?: boolean; strategy?: string },
    ) => {
      const text = (preset ?? input).trim();
      // F-012: the guard is the ref, set synchronously before the first await.
      // Previously only `streaming` guarded, and it was set AFTER the
      // conversation POST resolved — so a second send (double-tapped chip,
      // Enter + chip) during that round-trip opened a second conversation and
      // started a second stream, and Stop could only kill the newer one.
      if (!text || sendingRef.current) return;
      sendingRef.current = true;
      setSending(true);
      setAnnouncement("");
      setInput("");
      setError(null);
      track("tutor_question_sent", {
        reteach: opts?.reteach === true,
        subject_present: subject != null,
      });
      // One controller for the WHOLE turn: Stop aborts the conversation POST
      // and the stream, and a second send can never overwrite it (F-012).
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        let id = conversationId;
        if (!id) {
          try {
            const res = await post<ConversationOut>(
              "/tutor/conversations",
              {},
              { signal: controller.signal },
            );
            id = res.id;
            setConversationId(id);
            await refetchConvs();
          } catch (e) {
            // Stop pressed while the conversation POST was in flight.
            if ((e as { name?: string })?.name === "AbortError") return;
            setError(t("newChatFailed"));
            return;
          }
        }
        setMessages((m) => [
          ...m,
          { id: 0, role: "user", content: text, grounded: null, sources: [] },
        ]);
        setStreaming(true);
        const acc = { text: "" };
        try {
          const undone = await postStream<ChatDoneEvent>(
            `/tutor/conversations/${id}/messages/stream`,
            {
              message: text,
              subject,
              low_data: getLowData(),
              ...(opts?.reteach ? { reteach: true } : {}),
              // per-turn override wins over the composer's selection: the
              // follow-up chips ("explain simpler" / "give an example") carry
              // their own strategy without disturbing the picker state.
              ...((opts?.strategy ?? strategy)
                ? { strategy: opts?.strategy ?? strategy }
                : {}),
              ...(image ? { image } : {}),
            },
            (tok) => {
              acc.text += tok;
              scheduleTokenFlush(acc.text);
            },
            {
              signal: controller.signal,
              // The turn restarted on the fallback provider: the partial
              // text from the dead primary is orphaned half a sentence from
              // a turn the assistant no longer considers its own. Drop it
              // now, or the fallback answer renders appended to it.
              onReset: () => {
                acc.text = "";
                flushTokens();
                applyStreamedText("");
              },
            },
          );
          flushTokens();
          setMessages((m) => {
            const copy = [...m];
            let li = copy.findIndex((x) => x.id === undone.message_id);
            if (li < 0) {
              // The live-stream placeholder bubble carries id 0, so the real
              // message_id never matches it — merge into that trailing bubble
              // instead of pushing a second identical answer.
              for (let i = copy.length - 1; i >= 0; i--) {
                if (copy[i].role === "assistant" && copy[i].id === 0) {
                  li = i;
                  break;
                }
              }
            }
            const final = {
              id: undone.message_id,
              role: "assistant" as const,
              content: acc.text,
              grounded: undone.grounded,
              refused_reason: undone.refused_reason,
              sources: undone.sources ?? [],
              confidence: undone.confidence ?? null,
            };
            if (li >= 0) copy[li] = { ...copy[li], ...final };
            else copy.push(final);
            return copy;
          });
          // The answer is complete: announce it once, politely. The transcript
          // itself is no longer a live region, so tokens are not read aloud.
          setAnnouncement(acc.text);
          // Only now is the attachment discarded. Clearing it when the request
          // started meant a failed turn -- timeout, llm_unavailable, a stall --
          // showed the error and threw the student's photographed question away,
          // so the retry began by finding the photo again. The bubble above
          // carries the text, so the transcript is unaffected either way.
          if (image) setImage(null);
        } catch (e) {
          // Whatever arrived before the failure is the student's partial
          // answer; flush it so the bubble shows it.
          flushTokens();
          if ((e as { name?: string })?.name === "AbortError") return;
          setError(
            friendlyError((e as { rawDetail?: unknown }).rawDetail)?.text ??
              t("errorGeneric"),
          );
        }
      } finally {
        sendingRef.current = false;
        setSending(false);
        setStreaming(false);
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [
      applyStreamedText,
      input,
      conversationId,
      subject,
      refetchConvs,
      strategy,
      image,
      flushTokens,
      scheduleTokenFlush,
    ],
  );

  /**
   * Follow-up chips ("explain simpler" / "give an example") re-ask the
   * PREVIOUS question with an explicit strategy. Sending the chip's own
   * phrase as the message made retrieval search for "explain simpler", which
   * the coverage gate rightly refused (measured on the live build,
   * 2026-10-24). The question carries the corpus overlap; the strategy is
   * what the user is asking for — the same split as the composer's explicit
   * strategy chips.
   */
  const questionBefore = (index: number): string | undefined =>
    [...messages.slice(0, index)].reverse().find((x) => x.role === "user")
      ?.content;

  const resendWithStrategy = (index: number, key: string) => {
    const q = questionBefore(index);
    if (q) void send(q, { strategy: key });
  };

  const reteachFrom = (index: number) => {
    // 'আমি বুঝিন': re-ask the same question with the next teaching strategy
    // (server rotates conversation strategy).
    const q = questionBefore(index);
    if (q) void send(q, { reteach: true });
  };

  const regenerateFrom = (index: number) => {
    const q = questionBefore(index);
    if (q) void send(q);
  };

  const chooseStrategy = (next: string | null) => {
    setStrategy(next);
    if (next) track("tutor_strategy_chosen", { strategy: next });
  };

  // a wrong quiz item can arrive here as `location.state.explain` —
  // ask once, then drop the explain payload so a refresh does not re-ask.
  const quizContextRef = useRef(false);
  const [backToResult, setBackToResult] = useState(false);
  useEffect(() => {
    const st = location.state as {
      explain?: QuizExplainPayload;
      backToResult?: boolean;
    } | null;
    if (!st?.explain || quizContextRef.current) return;
    quizContextRef.current = true;
    if (st.backToResult) setBackToResult(true);
    void send(explainMessage(st.explain));
    void navigate(location.pathname, { replace: true, state: null });
  }, [location, navigate, send]);

  // the search box's "ask in Tutor" action hands the question over via
  // location.state.ask — ask it once, then clear the payload (like explain).
  const askSentRef = useRef(false);
  useEffect(() => {
    const st = location.state as { ask?: string } | null;
    if (!st?.ask || askSentRef.current) return;
    askSentRef.current = true;
    void send(st.ask);
    void navigate(location.pathname, { replace: true, state: null });
  }, [location, navigate, send]);

  const rate = async (messageId: number, rating: 1 | -1) => {
    try {
      await post("/feedback", { rating, message_id: messageId });
      setThanks(messageId);
      track("tutor_feedback", { rating });
      setTimeout(() => setThanks(null), 2000);
    } catch {
      // FE-07: a silently dropped thumbs rating reads as "registered" —
      // the student never learns their feedback went nowhere.
      toast(t("errorGeneric"));
    }
  };

  // Blueprint §26: any tutor answer can be kept in the student's saved notes.
  const saveNote = async (m: ChatMessage) => {
    try {
      await createNote({
        body: m.content,
        source: "tutor",
        source_ref: { subject },
      });
      setSavedId(m.id);
      track("note_saved", { source: "tutor" });
      toast(t("noteSaved"));
      setTimeout(() => setSavedId(null), 2000);
    } catch {
      // FE-07: the bookmark flipping back without a word made a lost note
      // indistinguishable from a slow network.
      toast(t("errorGeneric"));
    }
  };

  // attach an optional photo (question paper, whiteboard) to the next
  // turn. Server re-validates mime + decoded size and answers 422 image_invalid.
  const attachFile = (f: File | null) => {
    if (!f) return;
    // Two distinct refusals with two distinct sentences: a renamed non-image
    // (a PDF, a text snapshot) used to be reported as "too large", so the
    // student retried with a smaller file of the same unusable kind.
    if (!IMAGE_TYPES.includes(f.type)) {
      // C2 handoff: replace with a type-naming key ("only PNG/JPEG/WebP")
      // once i18n.ts has one; errImageInvalid is the closest shipped copy.
      setError(t("errImageInvalid"));
      return;
    }
    if (f.size > MAX_IMAGE_BYTES) {
      setError(t("imageTooLarge"));
      return;
    }
    const rd = new FileReader();
    rd.onload = () => {
      const res = asText(rd.result ?? "");
      const b64 = res.slice(res.indexOf(",") + 1);
      if (!b64) return;
      setImage({ mime_type: f.type, data_base64: b64 });
      track("tutor_image_attached", { kb: Math.round(f.size / 1024) });
    };
    rd.readAsDataURL(f);
  };

  // message search over this student's own history.
  const runSearch = async () => {
    const q = query.trim();
    if (q.length < 2) {
      setHits(null);
      return;
    }
    try {
      setHits(
        await get<MessageSearchHit[]>(
          `/tutor/messages/search?q=${encodeURIComponent(q)}`,
        ),
      );
    } catch {
      // FE-07: a failed search used to render exactly like "no results" —
      // the student concluded their old chat did not exist.
      setHits([]);
      toast(t("errorGeneric"));
    }
  };

  const commitRename = async (id: number) => {
    const title = renameValue.trim();
    setRenamingId(null);
    if (!title) return;
    try {
      await patch<ConversationOut>(`/tutor/conversations/${id}`, { title });
      await refetchConvs();
    } catch {
      // FE-07: the label snapped back to the old title with no feedback.
      toast(t("errorGeneric"));
    }
  };

  const removeConversation = async (id: number) => {
    if (!window.confirm(t("deleteChatConfirm"))) return;
    try {
      await del(`/tutor/conversations/${id}`);
      if (conversationId === id) {
        setConversationId(null);
        setMessages([]);
      }
      await refetchConvs();
    } catch {
      // FE-07: the chat vanished on screen then reappeared later — say the
      // delete did not go through.
      toast(t("errorGeneric"));
    }
  };

  return (
    <main id="main-content" tabIndex={-1} className="shell-main">
      <section className="section-head">
        <h2>{t("aiTutor")}</h2>
        <Button variant="soft" size="sm" onClick={newChat}>
          <MessageSquarePlus size={16} aria-hidden /> {t("newChat")}
        </Button>
      </section>

      {backToResult && (
        // back-link to the quiz result this explain loop came from.
        <Button
          variant="ghost"
          size="sm"
          className="section-gap-top"
          onClick={() => navigate("/student/quiz?result=1")}
        >
          <ArrowLeft size={16} aria-hidden /> {t("backToQuizResult")}
        </Button>
      )}

      <div className="chips chips-gap">
        {subjectOptions().map((s) => (
          <button
            key={s.value}
            className={subject === s.value ? "chip active" : "chip"}
            onClick={() => setSubject(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>

      <TutorHistory
        query={query}
        onQuery={setQuery}
        onSearch={() => void runSearch()}
        hits={hits}
        onOpenHit={(h) => {
          void loadConversation(h.conversation_id);
          setHits(null);
          setQuery("");
        }}
        conversations={conversations}
        conversationsError={conversationsError}
        onRetryConversations={() => void refetchConvs()}
        conversationId={conversationId}
        renamingId={renamingId}
        renameValue={renameValue}
        onRenameStart={(c) => {
          setRenamingId(c.id);
          setRenameValue(c.title ?? "");
        }}
        onRenameChange={setRenameValue}
        onRenameCommit={(id) => void commitRename(id)}
        onRenameCancel={() => setRenamingId(null)}
        onOpenConversation={(id) => void loadConversation(id)}
        onDeleteConversation={(id) => void removeConversation(id)}
      />

      <Card className="chat-card">
        {/* One polite announcement when an answer completes (F-016/F-064):
            the transcript used to be the live region itself, so every
            streamed token was announced as it arrived. */}
        <div
          className="visually-hidden"
          role="status"
          aria-live="polite"
          data-testid="tutor-announcer"
        >
          {announcement}
        </div>
        <TutorThread
          viewportRef={viewportRef}
          messages={messages}
          streaming={streaming}
          subject={subject}
          thanks={thanks}
          savedId={savedId}
          onSuggest={setInput}
          onPickImage={() => fileRef.current?.click()}
          onResendStrategy={resendWithStrategy}
          onReteach={reteachFrom}
          onRegenerate={regenerateFrom}
          onQuiz={(s) => navigate(`/student/quiz?subject=${s}`)}
          onPractice={() => navigate("/student/quiz")}
          onEvidence={setEvidence}
          onRate={(id, rating) => void rate(id, rating)}
          onSaveNote={(m) => void saveNote(m)}
        />

        <TutorComposer
          error={error}
          strategy={strategy}
          onStrategy={chooseStrategy}
          image={image}
          onRemoveImage={() => setImage(null)}
          onSendIntent={(text) => void send(text)}
          input={input}
          onInput={setInput}
          onSend={() => void send()}
          sending={sending}
          onStop={() => abortRef.current?.abort()}
          fileRef={fileRef}
          onAttach={attachFile}
          onTranscript={(text) =>
            setInput((cur) => (cur ? cur + " " + text : text))
          }
          showFootNote={!!me}
        />
      </Card>

      {evidence && (
        <EvidenceModal source={evidence} onClose={() => setEvidence(null)} />
      )}
    </main>
  );
}
