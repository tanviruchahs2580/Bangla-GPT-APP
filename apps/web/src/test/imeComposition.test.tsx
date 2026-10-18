/**
 * AUD-G-04: a Bangla phonetic/IME keyboard composes a word and confirms the
 * candidate with Enter. The tutor treated that confirmation as a submit, so a
 * half-composed word went out as the question. Every Enter handler on the page
 * has to ignore the key while `isComposing` is true.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AITutorPage from "../pages/student/AITutorPage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  createNote: vi.fn(),
}));

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

const me = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AITutorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
  apiMock.get.mockResolvedValue([]);
});

describe("tutor Enter handlers under an IME (AUD-G-04)", () => {
  it("does not send the question while the IME owns the Enter", async () => {
    renderPage();
    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    // `post` also carries fire-and-forget analytics events (as in
    // tutorSendRace.test.tsx); count only the conversation creates.
    const sendCalls = () =>
      apiMock.post.mock.calls.filter(
        ([path]) => path === "/tutor/conversations",
      );
    fireEvent.change(box, { target: { value: "কোষ কী" } });

    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(sendCalls()).toHaveLength(0);

    // The confirming Enter after composition ended still sends.
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(sendCalls()).toHaveLength(1));
  });

  it("does not search the history while the IME owns the Enter", async () => {
    renderPage();
    const search = await screen.findByRole("textbox", {
      name: t("searchHistory"),
    });
    const searchCalls = () =>
      apiMock.get.mock.calls.filter(([path]) =>
        String(path).includes("/tutor/messages/search"),
      );
    fireEvent.change(search, { target: { value: "ক্ষ" } });

    fireEvent.keyDown(search, { key: "Enter", isComposing: true });
    expect(searchCalls()).toHaveLength(0);

    fireEvent.keyDown(search, { key: "Enter" });
    await waitFor(() => expect(searchCalls()).toHaveLength(1));
  });
});
