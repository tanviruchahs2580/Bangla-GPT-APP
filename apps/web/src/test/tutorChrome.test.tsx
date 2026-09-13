/** WP-DR: tutor chrome — image intent menu, entry suggestions and the
 *  low-confidence hint. Streaming logic itself is untouched. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/tutor/conversations") return Promise.resolve([]);
    return Promise.resolve(null);
  });
  apiMock.post.mockResolvedValue({ id: 1 });
  apiMock.postStream.mockResolvedValue({
    message_id: 5,
    grounded: true,
    sources: [],
    confidence: 0.4,
  });
});

describe("WP-DR tutor chrome", () => {
  it("offers the four entry suggestions and the image intent menu after attach", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText(t("suggestTeach"))).toBeInTheDocument();
    expect(screen.getByText(t("suggestSolve"))).toBeInTheDocument();
    expect(screen.getByText(t("suggestQuizMe"))).toBeInTheDocument();
    expect(screen.getByText(t("suggestImage"))).toBeInTheDocument();

    // attach a small png and pick an intent: the message is the intent label
    const file = new File(["x"], "q.png", { type: "image/png" });
    const input = document.querySelector('input[type="file"]')!;
    await user.upload(input as HTMLElement, file);
    expect(await screen.findByText(t("imgPromptTitle"))).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: t("imgSolve") }));
    await waitFor(() =>
      expect(apiMock.postStream).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({
          message: t("imgSolve"),
          image: expect.objectContaining({ mime_type: "image/png" }),
        }),
        expect.anything(),
        expect.anything(),
      ),
    );
  });

  it("shows the low-confidence hint when the answer confidence is below 0.6", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(
      screen.getByPlaceholderText(t("askPlaceholder")),
      "কোষ কী?",
    );
    await user.click(screen.getByRole("button", { name: t("send") }));
    expect(await screen.findByText(t("lowConfidenceHint"))).toBeInTheDocument();
  });
});
