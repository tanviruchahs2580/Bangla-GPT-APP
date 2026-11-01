/** teacher Create hub — generate, filter, delete flows. */

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { CreateHub } from "../components/teacher/CreateHub";
import { t } from "../i18n";
import type { TeacherDocument, TeacherWorkload } from "../api";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
  downloadTeacherDocumentPdf: vi.fn(),
}));

vi.mock("../api", () => ({
  ...apiMock,
  apiBase: "/api",
  getToken: () => "tok",
}));

const DOC: TeacherDocument = {
  id: 9,
  kind: "worksheet",
  class_level: 6,
  subject: "science",
  chapter: "photosynthesis",
  title: "Photosynthesis worksheet",
  payload: {
    questions: [
      { question: "What is photosynthesis?", answer: "Food making in plants" },
    ],
  },
  created_at: "2026-09-01T10:00:00",
};

const WORKLOAD: TeacherWorkload = {
  counts: {
    worksheet: 1,
    answer_key: 0,
    homework: 0,
    rubric: 0,
    lesson_plan: 0,
  },
  minutes_saved: {
    worksheet: 25,
    answer_key: 0,
    homework: 0,
    rubric: 0,
    lesson_plan: 0,
  },
  total_minutes_saved: 25,
  estimate: true,
  methodology: "heuristic",
};

beforeEach(() => {
  apiMock.get.mockImplementation((path: string) => {
    if (path.startsWith("/teacher/documents"))
      return Promise.resolve([structuredClone(DOC)]);
    if (path === "/teacher/jobs") return Promise.resolve([]);
    if (path === "/teacher/workload")
      return Promise.resolve(structuredClone(WORKLOAD));
    return Promise.resolve(null);
  });
  apiMock.post.mockImplementation((path: string) => {
    if (path.startsWith("/teacher/generate/"))
      return Promise.resolve({ ...structuredClone(DOC), id: 10, sources: [] });
    return Promise.resolve(null);
  });
  apiMock.del.mockResolvedValue(null);
});

it("renders the saved library and the workload estimate", async () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateHub />
    </QueryClientProvider>,
  );
  expect(
    await screen.findByText("Photosynthesis worksheet"),
  ).toBeInTheDocument();
  expect(screen.getByText("25")).toBeInTheDocument();
});

it("generates a worksheet synchronously with the chosen class and subject", async () => {
  const user = userEvent.setup();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateHub />
    </QueryClientProvider>,
  );
  await screen.findByText("Photosynthesis worksheet");
  // Worksheet generation retrieves textbook evidence, so the API requires a
  // chapter (WorksheetIn.chapter is min_length=1). The old assertion clicked
  // Generate with the field empty and blessed a request the API answers 422;
  // the gate is asserted first, then the request with the chapter.
  const generate = screen.getByRole("button", { name: t("genNow") });
  expect(generate).toBeDisabled();
  fireEvent.change(
    screen.getByRole("textbox", { name: t("chapterRequired") }),
    {
      target: { value: "Photosynthesis" },
    },
  );
  expect(generate).toBeEnabled();
  await user.click(generate);
  await waitFor(() =>
    expect(apiMock.post).toHaveBeenCalledWith(
      "/teacher/generate/worksheet",
      expect.objectContaining({
        class_level: 6,
        subject: "science",
        chapter: "Photosynthesis",
      }),
    ),
  );
  expect(
    screen.getAllByText("Photosynthesis worksheet").length,
  ).toBeGreaterThanOrEqual(2);
});

it("answer key kind asks for questions; background run queues a job", async () => {
  const user = userEvent.setup();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateHub />
    </QueryClientProvider>,
  );
  await screen.findByText("Photosynthesis worksheet");
  // Segmented is a labelled toggle group now (M-17): role=button +
  // aria-pressed. The saved-library filter chips share the kind names, so
  // scope the query to the labelled group.
  const kindGroup = screen.getByRole("group", { name: t("genKind") });
  await user.click(
    within(kindGroup).getByRole("button", { name: t("genAnswerKey") }),
  );
  expect(screen.getByText(t("genQuestionsHint"))).toBeInTheDocument();
  fireEvent.change(
    screen.getByRole("textbox", { name: t("genQuestionsHint") }),
    {
      target: { value: "Q one\nQ two" },
    },
  );
  await user.click(screen.getByRole("button", { name: t("genLater") }));
  await waitFor(() =>
    expect(apiMock.post).toHaveBeenCalledWith(
      "/teacher/jobs",
      expect.objectContaining({ kind: "answer_key" }),
    ),
  );
});

it("delete removes the row via DELETE /teacher/documents/{id}", async () => {
  const user = userEvent.setup();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateHub />
    </QueryClientProvider>,
  );
  await screen.findByText("Photosynthesis worksheet");
  // Deleting a saved document is irreversible and regenerating it is work, so
  // it takes a second tap: the first arms the confirm, the second sends the
  // DELETE. The assertion between them is the point of the change -- one tap
  // must not destroy anything.
  await user.click(screen.getByRole("button", { name: t("deleteGeneric") }));
  expect(apiMock.del).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: t("confirmDelete") }));
  await waitFor(() =>
    expect(apiMock.del).toHaveBeenCalledWith("/teacher/documents/9"),
  );
  expect(
    screen.queryByText("Photosynthesis worksheet"),
  ).not.toBeInTheDocument();
});
