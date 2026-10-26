import { useRef } from "react";
import { cn } from "../lib/cn";

/**
 * A single-choice answer list with the APG radio-group contract.
 *
 * This existed twice: `QuizPage` had it and the chapter practice tab in
 * `LearnPage` did not. The tab announced `role="radio"` while every option sat
 * in the tab order — a keyboard-only student answered a 20-question quiz with
 * 80+ Tab presses and the arrow keys the role promises did nothing — which is
 * the defect `QuizPage` was fixed for. One implementation means the second
 * call site cannot drift from the first again.
 *
 * Contract: one tab stop for the whole group (roving `tabIndex`), arrow keys
 * move the selection AND the focus, Home/End jump to the ends.
 */
export function QuizOptionGroup({
  options,
  chosen,
  onChoose,
  label,
}: {
  options: string[];
  /** The chosen index, or nothing yet. `undefined` is accepted as well as
   *  `null` because `answers[current]` on a fresh map is `undefined` — the
   *  difference is invisible to the caller and made every option untabbable
   *  when it was not normalised here. */
  chosen: number | null | undefined;
  onChoose: (index: number) => void;
  /** Accessible name of the group — the question text at both call sites. */
  label: string;
}) {
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selected = chosen ?? null;

  return (
    <div
      className="stack"
      role="radiogroup"
      aria-label={label}
      // Programmatically focusable (not a tab stop): the keydown handler runs
      // on events bubbling from the radios, and this satisfies the jsx-a11y
      // focus contract for an interactive role.
      tabIndex={-1}
      onKeyDown={(e) => {
        const last = options.length - 1;
        if (last < 0) return;
        const focused = selected ?? 0;
        let next: number | null = null;
        if (e.key === "ArrowDown" || e.key === "ArrowRight")
          next = focused === last ? 0 : focused + 1;
        else if (e.key === "ArrowUp" || e.key === "ArrowLeft")
          next = focused === 0 ? last : focused - 1;
        else if (e.key === "Home") next = 0;
        else if (e.key === "End") next = last;
        if (next === null) return;
        e.preventDefault();
        onChoose(next);
        // Selection follows focus, so the roving tab stop moves too.
        optionRefs.current[next]?.focus();
      }}
    >
      {options.map((opt, oi) => (
        <button
          key={oi}
          ref={(el) => {
            optionRefs.current[oi] = el;
          }}
          role="radio"
          aria-checked={selected === oi}
          // Roving tab stop: the chosen option (or the first, before a choice
          // exists) is the group's single tab entry point.
          tabIndex={(selected === null ? oi === 0 : selected === oi) ? 0 : -1}
          className={cn("quiz-option", selected === oi && "selected")}
          onClick={() => onChoose(oi)}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}
