/** S3.3: curriculum coverage grid renders status badges in the teacher UI. */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TeacherDashboard from "../pages/TeacherDashboard";
import { t } from "../i18n";
import type { ClassRoom, Coverage } from "../types";

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

const ROOMS: ClassRoom[] = [
  { id: 1, class_level: 6, section: "GEN", student_count: 2 },
  { id: 2, class_level: 7, section: "GREEN", student_count: 1 },
];

const COV: Coverage = {
  subjects: ["bangla", "math", "science"],
  cells: [
    {
      classroom_id: 1,
      class_level: 6,
      section: "GEN",
      subject: "science",
      taught: true,
      attempts: 2,
      attempts_graded: 2,
      avg_score_pct: 85,
      status: "mastered",
    },
    {
      classroom_id: 1,
      class_level: 6,
      section: "GEN",
      subject: "math",
      taught: true,
      attempts: 1,
      attempts_graded: 1,
      avg_score_pct: 40,
      status: "practiced",
    },
    {
      classroom_id: 2,
      class_level: 7,
      section: "GREEN",
      subject: "bangla",
      taught: true,
      attempts: 0,
      attempts_graded: 0,
      avg_score_pct: null,
      status: "taught",
    },
  ],
};

function mockGet(cov: Coverage | null) {
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/teacher/classrooms")
      return Promise.resolve(structuredClone(ROOMS));
    if (path.endsWith("/roster")) return Promise.resolve([]);
    if (path === "/teacher/shorttests") return Promise.resolve([]);
    if (path === "/teacher/support-plans") return Promise.resolve([]);
    if (path === "/teacher/assignments") return Promise.resolve([]);
    if (path === "/teacher/curriculum-coverage")
      return Promise.resolve(cov && structuredClone(COV));
    return Promise.resolve(null);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGet(COV);
});

describe("S3.3 curriculum coverage card", () => {
  it("renders one row per class with a status badge per subject", async () => {
    render(<TeacherDashboard />);
    await screen.findByText(t("covTitle"));

    expect(screen.getByText("6 · GEN")).toBeInTheDocument();
    expect(screen.getByText("7 · GREEN")).toBeInTheDocument();
    expect(screen.getByText(t("covMastered"))).toBeInTheDocument();
    expect(screen.getByText(t("covPracticed"))).toBeInTheDocument();
    expect(screen.getByText(t("covTaught"))).toBeInTheDocument();
    // mastered badge is the positive tone; three grid cells have no cell data
    expect(document.querySelectorAll("span.badge-ok").length).toBe(1);
    expect(document.querySelectorAll("span.badge-teal").length).toBe(1);
    expect(screen.getAllByText("·").length).toBe(3);
  });

  it("shows the empty hint when nothing is covered yet", async () => {
    mockGet({ subjects: [], cells: [] });
    render(<TeacherDashboard />);
    await waitFor(() =>
      expect(screen.getByText(t("covEmpty"))).toBeInTheDocument(),
    );
    expect(apiMock.get).toHaveBeenCalledWith("/teacher/curriculum-coverage");
  });
});
