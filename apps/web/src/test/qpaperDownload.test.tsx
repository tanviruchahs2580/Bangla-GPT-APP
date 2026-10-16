/**
 * F-032: the question-paper PDF download used a raw fetch that bypassed the
 * shared client — no assertApiBaseUsable, no central 401 handling, no error
 * envelope, no timeout. It now goes through the shared getBlob() helper.
 * (The 401 -> global-handler wiring itself is covered in apiTimeouts.test.ts
 * against the real client.)
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QPaperReviewPanel } from "../components/teacher/QPaperReviewPanel";
import { t } from "../i18n";
import type { QPaper } from "../types";

const apiMock = vi.hoisted(() => ({
  getBlob: vi.fn(),
  post: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
}));

const QP: QPaper = {
  id: 1,
  class_level: 6,
  subject: "science",
  exam_type: "Exam",
  marks: 10,
  duration_min: 10,
  difficulty: { easy: 30, medium: 50, hard: 20 },
  chapters: ["kosh"],
  status: "draft",
  questions: [
    {
      ref: "q1",
      text: "TEXT q1",
      options: ["a", "b", "c", "d"],
      answer_index: 0,
      marks: 1,
      difficulty: "easy",
      chapter: "kosh",
      reviewed: false,
    },
  ],
  meta: {},
  reviewed_at: null,
  finalized_at: null,
  created_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.getBlob.mockResolvedValue({
    blob: new Blob(["pdf"], { type: "application/pdf" }),
    contentType: "application/pdf",
  });
  Object.assign(URL, {
    createObjectURL: vi.fn(() => "blob:qp"),
    revokeObjectURL: vi.fn(),
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("question paper download (F-032)", () => {
  it("downloads through the shared client instead of a raw fetch", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<QPaperReviewPanel qp={structuredClone(QP)} onChange={() => {}} />);

    await user.click(screen.getByRole("button", { name: "PDF" }));

    await waitFor(() =>
      expect(apiMock.getBlob).toHaveBeenCalledWith(
        "/teacher/qpapers/1/pdf?kind=paper",
      ),
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
  });

  it("shows the friendly error when the download fails", async () => {
    const user = userEvent.setup();
    apiMock.getBlob.mockRejectedValue(
      Object.assign(new Error("unauthorized"), {
        status: 401,
        code: "token_expired",
      }),
    );
    render(<QPaperReviewPanel qp={structuredClone(QP)} onChange={() => {}} />);

    await user.click(screen.getByRole("button", { name: "PDF+" }));

    // The failure is shown to the teacher, not swallowed.
    expect(await screen.findByRole("status")).toHaveTextContent(
      t("errorGeneric"),
    );
  });
});
