import { configure } from "@testing-library/dom";
import "@testing-library/jest-dom/vitest";

// RTL's default 1 s asyncUtilTimeout is below this app's cold render cost on a
// loaded runner: a full shuffled suite measured 1-2 failures per run where a
// page waited on several queries plus a lazy chunk (e.g.
// bulkassign.test.tsx "shows the per-student completion list" on 2026-10-29).
// The wait is a budget, not an assertion: an element that never appears still
// fails, and a present one resolves immediately, so no check is weakened.
configure({ asyncUtilTimeout: 8000 });

// jsdom does not implement Element.scrollTo; the chat viewport autoscrolls on update.
Element.prototype.scrollTo = () => {};
// ...nor Window.scrollTo, which App's ScrollToTop calls on every route change
// (jsdom logs "Not implemented" noise otherwise).
window.scrollTo = () => {};
