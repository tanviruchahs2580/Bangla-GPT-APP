/**
 * Text-to-speech capability detection for the chapter reader (AUD-G-12).
 *
 * `speechSynthesis` existing is not the same as having a Bangla voice: on a
 * device with only an English voice installed, `utter.lang = "bn-BD"` is
 * silently ignored and the reader hears Bangla text read with English
 * phonetics, or nothing at all. The reader therefore asks two questions
 * separately — is the engine there, and is a Bangla voice there — and tells the
 * reader which answer it got instead of deciding for them.
 */

export interface TtsSupport {
  /** The browser exposes a usable speech engine. */
  supported: boolean;
  /** A `bn*` voice is installed; null when none is found (or voices are not
   *  loaded yet — Chromium fills the list asynchronously and fires
   *  `voiceschanged`). */
  banglaVoice: SpeechSynthesisVoice | null;
}

/** Voice tags look like `bn-BD`, `bn_IN`, `bn`. */
const BANGLA_LANG = /^bn([-_]|$)/i;
const EXACT_BANGLA_BD = /^bn[-_]bd$/i;

/** Prefer an exact bn-BD voice, then any Bengali voice. */
export function pickBanglaVoice(
  voices: readonly SpeechSynthesisVoice[] | null | undefined,
): SpeechSynthesisVoice | null {
  if (!voices || voices.length === 0) return null;
  return (
    voices.find((v) => EXACT_BANGLA_BD.test(v.lang)) ??
    voices.find((v) => BANGLA_LANG.test(v.lang)) ??
    null
  );
}

/** The parts of `window` this module needs; injectable for tests. */
export interface TtsHost {
  speechSynthesis?: SpeechSynthesis | undefined;
  SpeechSynthesisUtterance?: unknown;
}

export function ttsSupport(
  host: TtsHost | undefined = typeof window !== "undefined"
    ? window
    : undefined,
): TtsSupport {
  if (!host?.speechSynthesis || !host.SpeechSynthesisUtterance) {
    return { supported: false, banglaVoice: null };
  }
  let voices: SpeechSynthesisVoice[] = [];
  try {
    voices = host.speechSynthesis.getVoices() ?? [];
  } catch {
    // A locked-down engine can throw here; that is "no voice found", not a
    // reason to hide the reader.
    voices = [];
  }
  return { supported: true, banglaVoice: pickBanglaVoice(voices) };
}

/** Ranges are the ones browsers honour for `SpeechSynthesisUtterance`. */
export const TTS_RATE = { min: 0.5, max: 1.5, step: 0.1, default: 0.9 };
export const TTS_PITCH = { min: 0.5, max: 2, step: 0.1, default: 1 };

/** Keep any stored or dragged value inside the engine's accepted range. */
export function clampTtsValue(
  value: number,
  bounds: { min: number; max: number },
) {
  if (!Number.isFinite(value)) return bounds.min;
  return Math.min(bounds.max, Math.max(bounds.min, value));
}

export function readTtsPrefs(storage: Pick<Storage, "getItem"> | undefined): {
  rate: number;
  pitch: number;
} {
  const fallback = { rate: TTS_RATE.default, pitch: TTS_PITCH.default };
  if (!storage) return fallback;
  try {
    const rate = Number(storage.getItem("ttsRate"));
    const pitch = Number(storage.getItem("ttsPitch"));
    return {
      rate:
        Number.isFinite(rate) && rate > 0
          ? clampTtsValue(rate, TTS_RATE)
          : fallback.rate,
      pitch:
        Number.isFinite(pitch) && pitch > 0
          ? clampTtsValue(pitch, TTS_PITCH)
          : fallback.pitch,
    };
  } catch {
    return fallback;
  }
}
