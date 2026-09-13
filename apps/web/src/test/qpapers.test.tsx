import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import CreatePage from "../pages/teacher/CreatePage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  ...apiMock,
  apiBase: "/api",
  getToken: () => "tok",
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/teacher/create?kind=question_paper"]}>
      <Routes>
        <Route path="/teacher/create" element={<CreatePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const ROOMS = [{ id: 1, class_level: 6, section: "GEN", student_count: 2 }];

const q = (ref: string) => ({
  ref,
  text: `TEXT ${ref}`,
  options: ["opt-a", "opt-b", "opt-c", "opt-d"],
  answer_index: 0,
  marks: 1,
  difficulty: "easy",
  chapter: "kosh",
  reviewed: false,
});

const DRAFT_BASE = () => ({
  id: 1,
  class_level: 6,
  subject: "science",
  exam_type: "Exam",
  marks: 10,
  duration_min: 10,
  difficulty: { easy: 30, medium: 50, hard: 20 },
  chapters: ["kosh"],
  status: "draft",
  questions: [q("q1"), q("q2"), q("q3")],
  meta: {},
  reviewed_at: null as string | null,
  finalized_at: null as string | null,
  created_at: null,
});

// Mutable paper the post-mock mutates, mirroring the API lifecycle.
let paper: ReturnType<typeof DRAFT_BASE>;

beforeEach(() => {
  vi.clearAllMocks();
  paper = DRAFT_BASE();
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/teacher/classrooms")
      return Promise.resolve(structuredClone(ROOMS));
    if (path.endsWith("/roster")) return Promise.resolve([]);
    if (path.includes("/analytics")) {
      return Promise.resolve({
        class_level: 6,
        students: 2,
        chapters: [],
        weak_chapters: [],
      });
    }
    return Promise.resolve(null);
  });
  apiMock.post.mockImplementation((path: string, body?: unknown) => {
    if (path === "/teacher/qpapers")
      return Promise.resolve(structuredClone(paper));
    if (path.endsWith("/review")) {
      const decisions = (
        body as { decisions: { ref: string; action: string; text?: string }[] }
      ).decisions;
      for (const d of decisions) {
        const question = paper.questions.find((x) => x.ref === d.ref);
        if (!question) continue;
        if (d.action === "edit" && d.text) question.text = d.text;
        question.reviewed = true;
      }
      if (paper.questions.every((x) => x.reviewed))
        paper.reviewed_at = "2026-09-06T00:00:00";
      return Promise.resolve(structuredClone(paper));
    }
    if (path.endsWith("/finalize")) {
      paper.status = "final";
      return Promise.resolve(structuredClone(paper));
    }
    if (path.endsWith("/replace")) {
      const ref = (body as { ref: string }).ref;
      const question = paper.questions.find((x) => x.ref === ref);
      if (question) {
        question.text = `REPLACED ${ref}`;
        question.reviewed = false;
      }
      return Promise.resolve(structuredClone(paper));
    }
    return Promise.resolve(null);
  });
});

async function openQpCard(user: ReturnType<typeof userEvent.setup>) {
  renderPage();
  await screen.findByLabelText(t("qpExamType"));
  await user.type(screen.getByLabelText(t("qpExamType")), "Exam 2026");
  await user.type(screen.getByLabelText(t("qpChaptersLabel")), "kosh, bol");
  await user.click(screen.getByRole("button", { name: t("qpGenerate") }));
  await screen.findByText("TEXT q1");
}

describe("S2.4 question paper builder", () => {
  it("generates a draft with the difficulty mix and shows questions", async () => {
    const user = userEvent.setup();
    await openQpCard(user);
    expect(apiMock.post).toHaveBeenCalledWith(
      "/teacher/qpapers",
      expect.objectContaining({
        class_level: 6,
        subject: "science",
        chapters: ["kosh", "bol"],
        exam_type: "Exam 2026",
        marks: 10,
        difficulty: { easy: 30, medium: 50, hard: 20 },
      }),
    );
    expect(screen.getByText("TEXT q2")).toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(t("qpNeedsReview"))),
    ).toBeInTheDocument();
  });

  it("blocks Finalize until every question is reviewed, then finalizes", async () => {
    const user = userEvent.setup();
    await openQpCard(user);
    const finalize = screen.getByRole("button", { name: t("qpFinalize") });
    expect(finalize).toBeDisabled();

    const footerAccept = screen
      .getAllByRole("button", { name: t("qpReviewAll") })
      .at(-1)!;
    await user.click(footerAccept);
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        "/teacher/qpapers/1/review",
        expect.objectContaining({
          decisions: [
            { ref: "q1", action: "accept" },
            { ref: "q2", action: "accept" },
            { ref: "q3", action: "accept" },
          ],
        }),
      ),
    );
    await waitFor(() => expect(finalize).toBeEnabled());
    await user.click(finalize);
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/teacher/qpapers/1/finalize"),
    );
    await waitFor(() =>
      expect(
        screen.getAllByText(new RegExp(t("qpFinalized"))).length,
      ).toBeGreaterThan(0),
    );
  });

  it("sends edit decisions with replacement text", async () => {
    const user = userEvent.setup();
    await openQpCard(user);
    await user.type(
      screen.getByLabelText(`${t("qpTitle")} 2`),
      "MY NEW QUESTION",
    );
    await user.click(
      screen.getAllByRole("button", { name: t("qpReviewAll") })[0],
    );
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith(
        "/teacher/qpapers/1/review",
        expect.objectContaining({
          decisions: [{ ref: "q1", action: "accept" }],
        }),
      ),
    );
  });

  it("replaces a single question", async () => {
    const user = userEvent.setup();
    await openQpCard(user);
    await user.click(
      screen.getAllByRole("button", { name: t("qpReplace") })[0],
    );
    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/teacher/qpapers/1/replace", {
        ref: "q1",
      }),
    );
    await waitFor(() =>
      expect(screen.getByText(/REPLACED q1/)).toBeInTheDocument(),
    );
  });
});
