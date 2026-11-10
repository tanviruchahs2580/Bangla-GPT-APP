/**
 * The জিজ্ঞাসা tab's accessibility contract.
 *
 * FE-FIX (a11y gaps): the ask input had a placeholder and no label — a
 * placeholder is a hint and it disappears as soon as the student types, leaving
 * the field unnamed to a screen reader — and neither the answer nor the "busy"
 * line was a live region, so a student using a reader heard nothing at all
 * after pressing Send. The tab also had no e2e coverage, which is why the axe
 * sweeps never saw it; that spec lives in e2e/w2-a11y.spec.ts.
 *
 * The chapter-practice numerals ride here too: the same tab pair printed
 * `done/total` and the score in Latin digits inside Bangla copy.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChapterAsk } from "../pages/student/learn/ChapterAsk";
import { ChapterPractice } from "../pages/student/learn/ChapterPractice";
import { setLang, t } from "../i18n";

const apiMock = vi.hoisted(() => ({ post: vi.fn() }));
const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

// The tabs import the client as "../../../api"; vitest keys mocks by resolved
// path, so this is the same module (the pattern learnStartError.test.tsx uses).
vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

const ANSWER = {
  answer: "সালোকসংশ্লেষণ গাছের পাতায় ঘটে।",
  grounded: true,
  sources: [{ chapter: "কোষ", book: "বিজ্ঞান" }],
};

beforeEach(() => {
  vi.clearAllMocks();
  setLang("bn");
  authMock.useAuth.mockReturnValue({
    me: { user_id: 1, role: "student", profile_id: 7, class_level: 6 },
    signOut: vi.fn(),
  });
  apiMock.post.mockResolvedValue(ANSWER);
});

describe("ChapterAsk accessibility", () => {
  it("labels the question field instead of relying on the placeholder", async () => {
    render(<ChapterAsk subject="science" chapter="কোষ" classLevel={6} />);
    const box = screen.getByRole("textbox", { name: t("askAboutChapter") });
    expect(box).toBeTruthy();
    // The label is a real <label for>, not just an aria-label.
    expect(box.id).toBeTruthy();
    expect(
      document.querySelector(`label[for="${box.id}"]`)?.textContent,
    ).toContain(t("askAboutChapter"));
  });

  it("announces the answer once, politely, from the answer node itself", async () => {
    const user = userEvent.setup();
    render(<ChapterAsk subject="science" chapter="কোষ" classLevel={6} />);

    // Nothing is announced before an answer exists.
    expect(screen.queryByRole("status")).toBeNull();

    await user.type(
      screen.getByRole("textbox", { name: t("askAboutChapter") }),
      "সালোকসংশ্লেষণ কী?",
    );
    await user.click(screen.getByRole("button", { name: t("send") }));

    // FE-FIX (a11y): the live semantics sit on the answer itself. The earlier
    // shape carried them on a second, visually-hidden copy of the same
    // sentence, which announced text the visible node already had and made
    // every `getByText` for an answer ambiguous — this test used to pin that
    // duplication (`findAllByText(...).length === 2`) as if it were the
    // contract. One node is the contract: the sentence appears exactly once,
    // and that element is the polite live region.
    const rendered = await screen.findAllByText(ANSWER.answer);
    expect(rendered).toHaveLength(1);

    const live = screen.getByRole("status");
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(live.textContent).toContain(ANSWER.answer);
  });

  it("announces the wait politely while the answer is in flight", async () => {
    const user = userEvent.setup();
    let release!: (v: unknown) => void;
    apiMock.post.mockImplementation(
      () =>
        new Promise((r) => {
          release = r;
        }),
    );
    render(<ChapterAsk subject="science" chapter="কোষ" classLevel={6} />);
    await user.type(
      screen.getByRole("textbox", { name: t("askAboutChapter") }),
      "সালোকসংশ্লেষণ কী?",
    );
    await user.click(screen.getByRole("button", { name: t("send") }));

    expect(await screen.findByText(t("thinking"))).toBeTruthy();
    expect(screen.getByText(t("thinking")).getAttribute("role")).toBe("status");
    release(ANSWER);
  });
});

describe("ChapterPractice numerals", () => {
  it("prints the question counter and the score in Bangla digits", async () => {
    const user = userEvent.setup();
    apiMock.post.mockImplementation((url: string) => {
      if (url === "/quizzes")
        return Promise.resolve({
          attempt_id: 5,
          requested: 1,
          questions: [
            {
              question_text: "প্রশ্ন",
              options: ["ক", "খ", "গ", "ঘ"],
              correct_index: 0,
              chapter: "কোষ",
              concept: "c",
            },
          ],
        });
      if (url === "/quizzes/5/submit")
        return Promise.resolve({
          attempt_id: 5,
          score_pct: 100,
          correct: 1,
          total: 1,
          review: [
            {
              question_text: "প্রশ্ন",
              is_correct: true,
              options: ["ক", "খ", "গ", "ঘ"],
              correct_index: 0,
            },
          ],
        });
      return Promise.resolve({});
    });

    render(<ChapterPractice subject="science" chapter="কোষ" classLevel={6} />);
    await user.click(screen.getByRole("button", { name: t("startQuiz") }));

    // "১/১", not "1/1" — the badge is Bangla copy like its neighbours.
    expect(await screen.findByText("১/১")).toBeTruthy();

    await user.click(screen.getByRole("radio", { name: /ক/ }));
    await user.click(screen.getByRole("button", { name: t("finishQuiz") }));
    expect(await screen.findByText("১০০%")).toBeTruthy();
  });
});
