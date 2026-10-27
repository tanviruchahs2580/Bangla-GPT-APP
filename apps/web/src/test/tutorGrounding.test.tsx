// Grounding-honesty regression tests for the streamed tutor.
//
// The server can no longer retract tokens it has already sent: when the
// primary provider dies mid-turn the turn restarts on the fallback, and the
// server emits an explicit `reset` event. These tests pin that the client
// honours it, and that an answer the server could not verify is still marked
// unsupported in the UI even though it arrives with zero citations.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import AITutorPage from "../pages/student/AITutorPage";
import { t } from "../i18n";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

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

const CONV = {
  id: 9,
  title: "Chat",
  created_at: "2026-09-08T00:00:00Z",
  message_count: 0,
};

const PARTIAL = "Truncated primary half";
const COMPLETE = "Complete fallback answer.";

const SOURCE = {
  book: "Science 6",
  chapter: "Kosh",
  section: "Kosh ki",
  page: 12,
  score: 0.9,
  excerpt: "Kosh ki?",
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

async function askAQuestion() {
  const user = userEvent.setup();
  renderPage();
  const box = await screen.findByRole("textbox", { name: t("askPlaceholder") });
  await user.type(box, "Kosh ki?{Enter}");
  await waitFor(() => expect(apiMock.postStream).toHaveBeenCalledTimes(1));
}

describe("Streamed tutor grounding honesty", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    apiMock.get.mockResolvedValue([]);
    apiMock.post.mockResolvedValue(CONV);
  });

  it("drops the partial text when the server restarts the turn on the fallback", async () => {
    apiMock.postStream.mockImplementation(
      async (
        _path: string,
        _body: unknown,
        onToken: (tok: string) => void,
        opts?: { onReset?: () => void },
      ) => {
        onToken(PARTIAL);
        opts?.onReset?.();
        onToken(COMPLETE);
        return {
          message_id: 4242,
          grounded: true,
          refused_reason: null,
          sources: [SOURCE],
        };
      },
    );

    await askAQuestion();

    // The answer text legitimately appears twice: in the transcript bubble
    // and in the polite live-region announcement ≤sr-only> that reads the
    // finished answer aloud. What must hold is that the DEAD turn's partial
    // text appears nowhere.
    await waitFor(() =>
      expect(screen.getAllByText(COMPLETE).length).toBeGreaterThan(0),
    );
    expect(
      screen.queryByText(PARTIAL),
      "the truncated primary output must not survive on screen",
    ).toBeNull();
    expect(
      screen.queryByText(PARTIAL + COMPLETE),
      "the partial and the restart must never be concatenated",
    ).toBeNull();
  });

  it("marks an unverifiable answer as unsupported even with no citations", async () => {
    // The server drops the sources when it cannot verify the answer against
    // the evidence. The badge must still render, otherwise an unverified
    // answer would reach the student looking exactly like a cited one.
    apiMock.postStream.mockImplementation(
      async (_path: string, _body: unknown, onToken: (tok: string) => void) => {
        onToken("Some invented text about the moon.");
        return {
          message_id: 4242,
          grounded: false,
          refused_reason: "citation_unverified",
          sources: [],
        };
      },
    );

    await askAQuestion();

    expect(await screen.findByText(t("unsupportedBadge"))).toBeTruthy();
    expect(screen.queryByText(t("supportedBadge"))).toBeNull();
  });

  it("marks an empty-completion answer as a failure, not a cited reply", async () => {
    apiMock.postStream.mockImplementation(
      async (_path: string, _body: unknown, onToken: (tok: string) => void) => {
        onToken("AI service unavailable.");
        return {
          message_id: 4242,
          grounded: false,
          refused_reason: "provider_empty",
          sources: [],
        };
      },
    );

    await askAQuestion();

    expect(await screen.findByText(t("unsupportedBadge"))).toBeTruthy();
    expect(screen.queryByText(t("supportedBadge"))).toBeNull();
  });
});
