/**
 * UX-001: classes with no corpus content are not an empty catalogue.
 *
 * `GET /learn/subjects?class_level=1` answers `[]` (not an error) for a class
 * the corpus has no books for — services/learn.py builds the list from the
 * loaded chunks — and the page fell straight through to an empty subject grid.
 * A Class-1 student tapped বিষয় and got a blank screen under a heading that
 * promised subjects. Two things are pinned here: the grid says what it knows,
 * and the class chips stop offering twelve classes as if all twelve existed.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LearnPage } from "../pages/student/LearnPage";
import { formatNumber, setLang, t } from "../i18n";
import type { SubjectOut } from "../types";

const apiMock = vi.hoisted(() => ({
  getSubjects: vi.fn(),
  getSubjectChapters: vi.fn(),
  getLearnProgress: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

/** The corpus: science for classes 6 and 7, nothing else. */
const CATALOGUE: SubjectOut[] = [
  { subject: "science", book: "বিজ্ঞান", class_levels: [6, 7] },
];

function renderPage(classLevel = 6) {
  authMock.useAuth.mockReturnValue({
    me: {
      user_id: 1,
      email: "s@x.com",
      role: "student",
      profile_id: 7,
      name: "S",
      class_level: classLevel,
    },
    signOut: vi.fn(),
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LearnPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The class chip's accessible name — the label plus the student's digits. */
const chipName = (c: number) => `${t("classLabel")} ${formatNumber(c)}`;

beforeEach(() => {
  vi.clearAllMocks();
  setLang("bn");
  apiMock.getSubjectChapters.mockResolvedValue([]);
  apiMock.getLearnProgress.mockResolvedValue([]);
  // The endpoint answers by `class_level`: the raw catalogue for the
  // unfiltered call the availability chips read, and the class's own slice
  // for the grid. The real API behaves exactly like this.
  apiMock.getSubjects.mockImplementation((classLevel?: number) =>
    Promise.resolve(
      classLevel === undefined
        ? structuredClone(CATALOGUE)
        : structuredClone(
            CATALOGUE.filter((s) => s.class_levels.includes(classLevel)),
          ),
    ),
  );
});

afterEach(() => cleanup());

describe("subject grid with no content for this class", () => {
  it("says the class has no content instead of rendering nothing", async () => {
    renderPage(1);

    expect(await screen.findByText(t("noSubjects"))).toBeInTheDocument();
    // The class's own list is empty AND the API said so — this is the only
    // branch that may say "no content"; a failed request still gets LoadError.
    expect(screen.queryByRole("alert")).toBeNull();
    const hint = await screen.findByText(/কনটেন্ট আছে এমন শ্রেণি/);
    // The classes that DO have content, in the student's own digits.
    expect(hint).toHaveTextContent("৬");
    expect(hint).toHaveTextContent("৭");
  });

  it("marks the content-less chips unavailable and keeps the rest selectable", async () => {
    renderPage(1);

    // The fixture corpus serves classes 6 and 7 only, so ten of the twelve
    // chips say why they are not selectable (in Bangla, on the accessible
    // name — a disabled chip is skipped by a pointer but not by a reader).
    const unavailable = await screen.findAllByRole("button", {
      name: new RegExp(t("classNoContent")),
    });
    expect(unavailable).toHaveLength(10);
    for (const chip of unavailable) expect(chip).toBeDisabled();

    for (const c of [6, 7]) {
      expect(screen.getByRole("button", { name: chipName(c) })).toBeEnabled();
    }
  });

  it("still claims nothing about availability when the catalogue fails", async () => {
    apiMock.getSubjects.mockImplementation((classLevel?: number) =>
      classLevel === undefined
        ? Promise.reject(new Error("boom"))
        : Promise.resolve([]),
    );
    renderPage(1);

    // No evidence, no disabled chips: the empty state stands on the class's
    // own (successful) answer, and every chip stays selectable.
    expect(await screen.findByText(t("noSubjects"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: chipName(2) })).toBeEnabled();
    expect(
      screen.queryByRole("button", {
        name: new RegExp(t("classNoContent")),
      }),
    ).toBeNull();
  });
});
