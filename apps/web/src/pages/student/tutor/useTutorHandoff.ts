import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  explainMessage,
  type QuizExplainPayload,
} from "../../../lib/quizExplain";

/**
 * The two handoffs that arrive as `location.state`: the search box's "ask in
 * Tutor" question and the quiz result's "explain this" payload. Each turn is
 * sent once, then the payload is dropped from history so a refresh or a back
 * navigation does not re-ask it.
 *
 * The send is deferred one macrotask. StrictMode mounts the tutor twice in
 * dev: the first instance's send raced the simulated unmount, whose cleanup
 * aborts the in-flight turn while the payload had already been cleared — so
 * the handoff opened a conversation and then showed an empty thread (measured
 * by this stream's STU-12 and STU-11 flows). Deferring lets the discarded
 * instance step aside (its timer is cleared) and the surviving one perform
 * the turn; in production the send is one tick later and nothing else changes.
 */
export function useTutorHandoff(
  send: (text: string) => void,
  onResultContext: (fromQuizResult: boolean) => void,
): void {
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as {
    ask?: string;
    explain?: QuizExplainPayload;
    backToResult?: boolean;
  } | null;
  const alive = useRef(false);
  const runRef = useRef<() => void>(() => {});

  useEffect(() => {
    runRef.current = () => {
      // Re-read at call time: the payload may already have been consumed.
      const st = location.state as {
        ask?: string;
        explain?: QuizExplainPayload;
        backToResult?: boolean;
      } | null;
      if (st?.explain) {
        if (st.backToResult) onResultContext(true);
        send(explainMessage(st.explain));
      } else if (st?.ask) {
        send(st.ask);
      } else {
        return;
      }
      void navigate(location.pathname, { replace: true, state: null });
    };
  });

  useEffect(() => {
    if (!state?.ask && !state?.explain) return;
    alive.current = true;
    const id = window.setTimeout(() => {
      if (alive.current) runRef.current();
    }, 0);
    return () => {
      alive.current = false;
      window.clearTimeout(id);
    };
  }, [state?.ask, state?.explain]);
}
