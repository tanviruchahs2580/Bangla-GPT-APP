import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { t } from "../i18n";
import { hasBanglaTtsVoice } from "../lib/progress";
import { LearnChapterPage } from "../pages/student/LearnPage";

// F-108: with speechSynthesis but no Bengali voice, the Listen button used to
// speak Bangla text through an English voice with no explanation. It must be
// disabled with a reason until a `bn*` voice exists.
const apiMock = vi.hoisted(() => ({
  getChapterContent: vi.fn(),
  getLearnProgress: vi.fn(),
  getSubjectChapters: vi.fn(),
  getSubjects: vi.fn(),
  post: vi.fn(),
  upsertLearnProgress: vi.fn(),
}));

const authMock = vi.hoisted(() => ({ useAuth: vi.fn() }));

vi.mock("../api", () => apiMock);
vi.mock("../AuthContext", () => authMock);

class FakeUtterance {
  text: string;
  lang = "";
  voice: unknown = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
  }
}

interface SynthMock {
  getVoices(): { lang: string }[];
  speak: ReturnType<typeof vi.fn>;
  cancel: ReturnType<typeof vi.fn>;
  addEventListener(type: string, fn: () => void): void;
  removeEventListener(type: string, fn: () => void): void;
  setVoices(voices: { lang: string }[]): void;
  fireVoicesChanged(): void;
}

function installSpeechSynthesis(initial: { lang: string }[]): SynthMock {
  let voices = initial;
  const listeners = new Set<() => void>();
  const synth: SynthMock = {
    getVoices: () => voices,
    speak: vi.fn(),
    cancel: vi.fn(),
    addEventListener: (type, fn) => {
      if (type === "voiceschanged") listeners.add(fn);
    },
    removeEventListener: (_type, fn) => {
      listeners.delete(fn);
    },
    setVoices: (next) => {
      voices = next;
    },
    fireVoicesChanged: () => listeners.forEach((fn) => fn()),
  };
  Object.defineProperty(window, "speechSynthesis", {
    configurable: true,
    value: synth,
  });
  return synth;
}

function renderReader() {
  window.history.pushState(
    {},
    "",
    `/student/learn/science/${encodeURIComponent("কোষ")}?class=6`,
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LearnChapterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Bengali voice guard for read-aloud", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
    authMock.useAuth.mockReturnValue({
      me: {
        user_id: 1,
        email: "s@x.com",
        role: "student",
        profile_id: 7,
        name: "S",
        class_level: 6,
      },
      signOut: vi.fn(),
    });
    apiMock.getChapterContent.mockResolvedValue({
      subject: "science",
      class_level: 6,
      book: "বিজ্ঞান",
      chapter: "কোষ",
      sections: [{ section: "কোষ", text: "কোষ হলো জীবের গঠনমূলক একক।" }],
    });
    apiMock.getLearnProgress.mockResolvedValue([]);
    apiMock.upsertLearnProgress.mockResolvedValue({});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    // @ts-expect-error -- removing the mock exposes undefined, as in jsdom.
    delete window.speechSynthesis;
  });

  it("accepts only a bn* voice as usable", () => {
    expect(hasBanglaTtsVoice([])).toBe(false);
    expect(hasBanglaTtsVoice([{ lang: "en-US" }])).toBe(false);
    expect(hasBanglaTtsVoice([{ lang: "bn-BD" }])).toBe(true);
    expect(hasBanglaTtsVoice([{ lang: "EN-US" }, { lang: "bn-IN" }])).toBe(
      true,
    );
  });

  it("disables the Listen button and names the reason when only en voices exist", async () => {
    installSpeechSynthesis([{ lang: "en-US" }]);
    renderReader();
    const listen = await screen.findByRole("button", { name: t("listen") });
    await waitFor(() => expect(listen).toBeDisabled());
    expect(listen).toHaveAttribute("title", t("ttsUnavailable"));
  });

  it("enables the button and speaks with the Bengali voice when one exists", async () => {
    const user = userEvent.setup();
    const bnVoice = { lang: "bn-BD" };
    const synth = installSpeechSynthesis([bnVoice]);
    renderReader();
    const listen = await screen.findByRole("button", { name: t("listen") });
    await waitFor(() => expect(listen).toBeEnabled());
    expect(listen).not.toHaveAttribute("title");

    await user.click(listen);
    expect(synth.speak).toHaveBeenCalledTimes(1);
    const utterance = synth.speak.mock.calls[0][0] as FakeUtterance;
    expect(utterance.lang).toBe("bn-BD");
    expect(utterance.voice).toBe(bnVoice);
    expect(utterance.text).toContain("কোষ");
  });

  it("picks the voice up when the browser reports the list asynchronously", async () => {
    const synth = installSpeechSynthesis([]);
    renderReader();
    const listen = await screen.findByRole("button", { name: t("listen") });
    await waitFor(() => expect(listen).toBeDisabled());

    synth.setVoices([{ lang: "bn-BD" }]);
    act(() => synth.fireVoicesChanged());
    await waitFor(() => expect(listen).toBeEnabled());
  });
});
