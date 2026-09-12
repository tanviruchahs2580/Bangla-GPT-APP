// Regression (Phase H live user test, 2026-09-08): the live-stream placeholder
// bubble is created with id 0 while the done event carries the REAL server
// message_id. The old finalize path only matched by message_id, so every
// streamed answer was pushed a SECOND time -- the student saw the same answer
// rendered twice. The fix merges the done payload into the trailing id-0
// assistant bubble. This test pins that contract.
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

const CONV = {
  id: 9,
  title: "Chat",
  created_at: "2026-09-08T00:00:00Z",
  message_count: 0,
};
const ANSWER = "Kosh is the smallest unit of life. Answer text.";

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

describe("Tutor stream finalize dedup (Phase H)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    apiMock.get.mockResolvedValue([]); // conversations list + search
    apiMock.post.mockResolvedValue(CONV); // new conversation
    // Stream one token, then resolve the done event with the REAL message id.
    apiMock.postStream.mockImplementation(
      async (_path: string, _body: unknown, onToken: (tok: string) => void) => {
        onToken(ANSWER);
        return {
          message_id: 4242,
          grounded: true,
          refused_reason: null,
          sources: [
            {
              book: "Science 6",
              chapter: "Kosh",
              section: "Kosh ki",
              page: 12,
              score: 0.9,
              excerpt: "Kosh ki?",
            },
          ],
        };
      },
    );
  });

  it("renders the streamed answer exactly once after the done event", async () => {
    const user = userEvent.setup();
    renderPage();

    const box = await screen.findByRole("textbox", {
      name: t("askPlaceholder"),
    });
    await user.type(box, "Kosh ki?{Enter}");

    await waitFor(() => expect(apiMock.postStream).toHaveBeenCalledTimes(1));
    // The answer must appear in exactly ONE bubble: the placeholder merged
    // with the done payload, never a second pushed copy.
    await waitFor(() => expect(screen.getAllByText(ANSWER)).toHaveLength(1));
    // And the merged bubble must carry the grounded badge (done payload applied).
    expect(await screen.findByText(t("supportedBadge"))).toBeTruthy();
  });
});
