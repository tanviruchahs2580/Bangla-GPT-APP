/** AUD-G-12 / G-26: Bangla-voice detection, reader controls, no autoplay. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { LearnChapterPage } from "../pages/student/LearnPage";
import {
  TTS_PITCH,
  TTS_RATE,
  clampTtsValue,
  pickBanglaVoice,
  readTtsPrefs,
  ttsSupport,
} from "../lib/tts";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  postStream: vi.fn(),
  getChapterContent: vi.fn(),
  getLearnProgress: vi.fn(),
  getSubjectChapters: vi.fn(),
  getSubjects: vi.fn(),
  upsertLearnProgress: vi.fn(),
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

const voice = (lang: string, name = lang): SpeechSynthesisVoice => ({
  lang,
  name,
  default: false,
  localService: true,
  voiceURI: name,
});

describe("pickBanglaVoice", () => {
  it("prefers an exact bn-BD voice over other Bengali locales", () => {
    expect(pickBanglaVoice([voice("bn-IN"), voice("bn-BD")])?.lang).toBe(
      "bn-BD",
    );
  });

  it("falls back to any bn* voice, then to null", () => {
    expect(pickBanglaVoice([voice("en-US"), voice("bn-IN")])?.lang).toBe(
      "bn-IN",
    );
    expect(pickBanglaVoice([voice("en-US")])).toBeNull();
    expect(pickBanglaVoice([])).toBeNull();
    expect(pickBanglaVoice(undefined)).toBeNull();
  });
});

describe("ttsSupport", () => {
  it("reports unsupported when the engine is missing", () => {
    expect(ttsSupport(undefined).supported).toBe(false);
    expect(ttsSupport({ speechSynthesis: undefined }).supported).toBe(false);
  });

  it("separates engine support from Bangla-voice availability", () => {
    const engine = (voices: SpeechSynthesisVoice[]) =>
      ({ getVoices: () => voices }) as unknown as SpeechSynthesis;
    expect(
      ttsSupport({
        speechSynthesis: engine([voice("en-GB")]),
        SpeechSynthesisUtterance: function () {},
      }),
    ).toEqual({ supported: true, banglaVoice: null });

    expect(
      ttsSupport({
        speechSynthesis: engine([voice("bn-BD")]),
        SpeechSynthesisUtterance: function () {},
      }).banglaVoice?.lang,
    ).toBe("bn-BD");
  });
});

describe("speech controls", () => {
  it("clamps out-of-range and non-numeric values", () => {
    expect(clampTtsValue(5, TTS_RATE)).toBe(TTS_RATE.max);
    expect(clampTtsValue(0.1, TTS_PITCH)).toBe(TTS_PITCH.min);
    expect(clampTtsValue(Number.NaN, TTS_RATE)).toBe(TTS_RATE.min);
  });

  it("reads stored preferences, ignoring junk", () => {
    const store = (map: Record<string, string>) => ({
      getItem: (k: string) => map[k] ?? null,
    });
    expect(readTtsPrefs(store({}))).toEqual({
      rate: TTS_RATE.default,
      pitch: TTS_PITCH.default,
    });
    expect(readTtsPrefs(store({ ttsRate: "1.2", ttsPitch: "nope" }))).toEqual({
      rate: 1.2,
      pitch: TTS_PITCH.default,
    });
    expect(readTtsPrefs(store({ ttsRate: "99" })).rate).toBe(TTS_RATE.max);
  });
});

describe("chapter reader TTS", () => {
  const speak = vi.fn();
  const cancel = vi.fn();
  let lastUtterance: {
    text: string;
    lang: string;
    rate: number;
    pitch: number;
    voice: SpeechSynthesisVoice | null;
  } | null = null;

  function installEngine(voices: SpeechSynthesisVoice[]) {
    class FakeUtterance {
      text: string;
      lang = "";
      rate = 1;
      pitch = 1;
      voice: SpeechSynthesisVoice | null = null;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor(text: string) {
        this.text = text;
      }
    }
    Object.defineProperty(window, "SpeechSynthesisUtterance", {
      configurable: true,
      writable: true,
      value: FakeUtterance,
    });
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      writable: true,
      value: {
        speak: (u: unknown) => {
          lastUtterance = u as typeof lastUtterance;
          speak(u);
        },
        cancel,
        getVoices: () => voices,
      },
    });
  }

  function renderChapter() {
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

  beforeEach(() => {
    vi.clearAllMocks();
    lastUtterance = null;
    localStorage.clear();
    authMock.useAuth.mockReturnValue({ me, signOut: vi.fn() });
    window.history.pushState({}, "", "/student/learn/science/কোষ?class=6");
    apiMock.get.mockResolvedValue([]);
    apiMock.getLearnProgress.mockResolvedValue([]);
    apiMock.upsertLearnProgress.mockResolvedValue({});
    apiMock.getChapterContent.mockResolvedValue({
      subject: "science",
      chapter: "কোষ",
      book: "বিজ্ঞান",
      class_level: 6,
      sections: [{ section: "কোষ কী", text: "জীবদেহের একক।" }],
    });
  });

  it("never speaks on its own, and speaks with the bn voice on click", async () => {
    installEngine([voice("bn-BD", "Bangla")]);
    const user = userEvent.setup();
    renderChapter();

    const button = await screen.findByRole("button", { name: /শুনুন/ });
    expect(speak).not.toHaveBeenCalled(); // no autoplay

    await user.click(button);
    expect(speak).toHaveBeenCalledTimes(1);
    expect(lastUtterance?.lang).toBe("bn-BD");
    expect(lastUtterance?.voice?.lang).toBe("bn-BD");
    expect(lastUtterance?.rate).toBe(TTS_RATE.default);
  });

  it("tells the reader when no Bangla voice is installed instead of failing silently", async () => {
    installEngine([voice("en-GB")]);
    const user = userEvent.setup();
    renderChapter();

    await user.click(await screen.findByRole("button", { name: /শুনুন/ }));
    await waitFor(() =>
      expect(
        screen.getByText(/বাংলা কণ্ঠস্বর পাওয়া যায়নি/),
      ).toBeInTheDocument(),
    );
    // The fallback still reads the chapter, with the engine's default voice.
    expect(speak).toHaveBeenCalledTimes(1);
    expect(lastUtterance?.voice).toBeNull();
  });

  it("applies the reader's rate and pitch and persists them", async () => {
    installEngine([voice("bn-BD")]);
    const user = userEvent.setup();
    renderChapter();

    await screen.findByRole("button", { name: /শুনুন/ });
    const rate = screen.getByLabelText(/পড়ার গতি/);
    fireEvent.change(rate, { target: { value: "1.3" } });
    await user.click(screen.getByRole("button", { name: /শুনুন/ }));

    expect(lastUtterance?.rate).toBeCloseTo(1.3);
    expect(localStorage.getItem("ttsRate")).toBe("1.3");
  });

  it("says the engine is missing instead of hiding the feature", async () => {
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: undefined,
    });
    renderChapter();
    expect(
      await screen.findByText(/পড়ে শোনানোর সুবিধা নেই/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /শুনুন/ })).toBeNull();
  });
});
