/** RENO: accessibility sweep across the redesigned surfaces (axe-core,
 *  WCAG 2.1 A/AA). color-contrast excluded: jsdom cannot compute real
 *  styles (same documented limitation as axeWelcome). Serious + critical
 *  violations fail the suite. Covers: student home/practice/tutor/me,
 *  teacher home/classes/assessments/analytics/profile, and the new
 *  shared ui primitives (Modal open state included).
 */
import axe from "axe-core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "../components/ui";
import HomePage from "../pages/student/HomePage";
import MePage from "../pages/student/MePage";
import QuizPage from "../pages/student/QuizPage";
import AnalyticsPage from "../pages/teacher/AnalyticsPage";
import AssessmentsPage from "../pages/teacher/AssessmentsPage";
import ClassesPage from "../pages/teacher/ClassesPage";
import TeacherHomePage from "../pages/teacher/TeacherHomePage";
import TeacherProfilePage from "../pages/teacher/TeacherProfilePage";

// Universal api mock: every real named export becomes a resolving stub so
// the sweep only cares about rendered a11y, not data shapes. Shapes follow
// each endpoint's contract closely enough to render real (empty) states.
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  const shapeFor = (path: string): unknown => {
    if (path.includes("classrooms") || path.includes("support-plans"))
      return [];
    if (path.includes("memory"))
      return { memory_enabled: true, facts: {}, on_disable_note_code: "x" };
    return null; // every other caller guards null as "empty/not loaded"
  };
  const mock: Record<string, unknown> = {};
  for (const key of Object.keys(actual)) {
    if (key === "get") {
      mock[key] = vi.fn((path: string) => Promise.resolve(shapeFor(path)));
    } else if (key === "getMyMemory") {
      mock[key] = vi.fn(() =>
        Promise.resolve({
          memory_enabled: true,
          facts: {},
          on_disable_note_code: "x",
        }),
      );
    } else {
      mock[key] = vi.fn(() => Promise.resolve(null));
    }
  }
  mock.apiBase = "/api";
  return mock;
});

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

const teacher = { ...me, role: "teacher", profile_id: 3 };

async function axeExpect(name: string, ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const { container } = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
  const results = await axe.run(container, {
    runOnly: ["wcag2a", "wcag2aa", "best-practice"],
    rules: { "color-contrast": { enabled: false } },
  });
  const blocking = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(blocking.map((v) => `${name}: ${v.id}: ${v.help}`)).toEqual([]);
}

describe("RENO accessibility sweep (student + teacher + primitives)", () => {
  it("student surfaces are clean", async () => {
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    await axeExpect("home", <HomePage />);
    await axeExpect("practice", <QuizPage />);
    await axeExpect("me", <MePage />);
  }, 40000);

  it("teacher surfaces are clean", async () => {
    authMock.useAuth.mockReturnValue({ me: teacher, signOut: vi.fn() });
    await axeExpect("teacher-home", <TeacherHomePage />);
    await axeExpect("teacher-classes", <ClassesPage />);
    await axeExpect("teacher-assessments", <AssessmentsPage />);
    await axeExpect("teacher-analytics", <AnalyticsPage />);
    await axeExpect("teacher-profile", <TeacherProfilePage />);
  }, 40000);

  it("shared Modal primitive is clean while open", async () => {
    await axeExpect(
      "modal",
      <Modal open onClose={vi.fn()} title="Dialog">
        <button>act</button>
      </Modal>,
    );
  }, 40000);
});
