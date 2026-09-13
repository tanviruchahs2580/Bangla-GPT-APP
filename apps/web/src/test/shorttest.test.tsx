import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import CreatePage from "../pages/teacher/CreatePage";
import { t } from "../i18n";
import type { ShortTest } from "../types";

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
    <MemoryRouter initialEntries={["/teacher/create?kind=short_test"]}>
      <Routes>
        <Route path="/teacher/create" element={<CreatePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const ROOMS = [{ id: 1, class_level: 6, section: "GEN", student_count: 2 }];

const ROSTER = [
  {
    student_id: 11,
    name: "Rahim",
    class_level: 6,
    email: "rahim@school.edu",
    invite_pending: false,
    attempts_graded: 1,
    avg_score_pct: 60,
  },
  {
    student_id: 12,
    name: "Karim",
    class_level: 6,
    email: null,
    invite_pending: false,
    attempts_graded: 1,
    avg_score_pct: 40,
  },
];

const EMPTY_ANALYTICS = {
  class_level: 6,
  students: 2,
  chapters: [],
  weak_chapters: [],
  students_detail: [],
};

const ASSIGNED: ShortTest = {
  id: 7,
  classroom_id: 1,
  teacher_id: 3,
  subject: "science",
  chapter: "kosh",
  num_questions: 5,
  duration_min: 10,
  questions: [
    { id: "q1", question_text: "Q one", options: ["a", "b", "c", "d"] },
    { id: "q2", question_text: "Q two", options: ["a", "b", "c", "d"] },
  ],
  attempts: [
    { student_id: 11, attempt_id: 21 },
    { student_id: 12, attempt_id: 22 },
  ],
  created_at: "2026-09-03T09:00:00",
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/teacher/classrooms")
      return Promise.resolve(structuredClone(ROOMS));
    if (path.endsWith("/roster"))
      return Promise.resolve(structuredClone(ROSTER));
    if (path === "/teacher/shorttests") return Promise.resolve([]);
    if (path.includes("/analytics"))
      return Promise.resolve(structuredClone(EMPTY_ANALYTICS));
    return Promise.resolve(null);
  });
  apiMock.post.mockImplementation((path: string) => {
    if (path === "/teacher/shorttests")
      return Promise.resolve(structuredClone(ASSIGNED));
    return Promise.resolve(null);
  });
});

describe("S2.5 short test assignment card", () => {
  it("assigns one chapter test to the whole classroom", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(t("stEmpty"));

    // empty state until something is assigned
    expect(screen.getByText(t("stEmpty"))).toBeInTheDocument();

    const assignBtn = screen.getByRole("button", { name: t("stAssign") });
    expect(assignBtn).toBeDisabled(); // no chapter typed yet

    await user.type(screen.getByLabelText(t("stChapterLabel")), "kosh");
    expect(assignBtn).toBeEnabled();
    await user.click(assignBtn);

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/teacher/shorttests", {
        classroom_id: 1,
        subject: "science",
        chapter: "kosh",
        num_questions: 5,
        duration_min: 10,
      }),
    );
    // confirmation names how many students got an attempt
    expect(
      await screen.findByText(t("stAssigned", { n: 2 })),
    ).toBeInTheDocument();
    // the assignment appears in the recent list
    expect(screen.getByText(/kosh/)).toBeInTheDocument();
    expect(screen.queryByText(t("stEmpty"))).not.toBeInTheDocument();
  });
});
