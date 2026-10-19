/**
 * Shared harness for AITutorPage test suites (chatFeedback, evidenceModal):
 * the fixtures, the render helper, the ask-through-the-UI helper and the
 * common beforeEach wiring used to be copy-pasted into each file -- the
 * duplication ratchet flagged the clone
 * (apps/api/quality-baselines/duplication-baseline.json).
 *
 * The `vi.hoisted` mock surface itself must stay in each suite's own file:
 * `vi.mock` factories run before module imports, so sharing them through a
 * module import crashes the worker in this vitest build (measured; the async
 * factory form fails with "Worker exited unexpectedly"). What CAN be shared
 * -- everything that runs after the mocks exist -- lives here.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import AITutorPage from "../pages/student/AITutorPage";
import { t } from "../i18n";

export interface ApiMocks {
  get: ReturnType<typeof vi.fn>;
  post: ReturnType<typeof vi.fn>;
  postStream: ReturnType<typeof vi.fn>;
  patch: ReturnType<typeof vi.fn>;
  del: ReturnType<typeof vi.fn>;
}

export interface AuthMocks {
  useAuth: ReturnType<typeof vi.fn>;
}

export const ME = {
  user_id: 1,
  email: "s@x.com",
  role: "student",
  profile_id: 7,
  name: "S",
  class_level: 6,
};

// ASCII fixture fields keep assertions byte-safe (no Bengali literals here).
export const SOURCE = {
  book: "Biggan",
  chapter: "Kosh-Excerpt-Chapter",
  section: "Cell-Ki",
  page: 12,
  score: 4.2,
  excerpt: "Koash hosse jibdeher ekok. Sanitized excerpt line two.",
};

export const ANSWER_TEXT = "Koash hosse ekok.";

/** The standard beforeEach wiring: fresh mocks, one streamed grounded answer. */
export function wireTutorMocks(apiMock: ApiMocks, authMock: AuthMocks): void {
  vi.clearAllMocks();
  authMock.useAuth.mockReturnValue({ me: ME, signOut: vi.fn() });
  apiMock.get.mockResolvedValue([]);
  apiMock.post.mockResolvedValue({
    id: 1,
    title: null,
    created_at: "2026-01-01T00:00:00Z",
    message_count: 0,
    last_strategy: null,
  });
  apiMock.postStream.mockImplementation(
    async (_url: string, _body: unknown, onToken: (tok: string) => void) => {
      onToken(ANSWER_TEXT);
      return {
        message_id: 2,
        user_message_id: 1,
        answer: ANSWER_TEXT,
        grounded: true,
        sources: [SOURCE],
      };
    },
  );
}

export function renderTutorPage() {
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

/** Ask one question through the UI; resolves once the answer actions exist. */
export async function askOneQuestion(user: ReturnType<typeof userEvent.setup>) {
  const box = await screen.findByRole("textbox", { name: t("askPlaceholder") });
  await user.type(box, "k");
  await user.keyboard("{Enter}");
  return screen.findByRole(
    "button",
    { name: t("copyAnswer") },
    { timeout: 5000 },
  );
}
