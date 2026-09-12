/**
 * S1.12: Web Speech API (bn-BD) voice input helpers.
 *
 * The API ships unprefixed only in recent Chromium; Safari still hides it
 * behind webkitSpeechRecognition (and does not support bn-BD recognition).
 * Everything here is feature-detected: when absent, VoiceButton renders
 * nothing and typing keeps working.
 */

export interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult:
    | ((event: {
        results: ArrayLike<ArrayLike<{ transcript: string }>>;
      }) => void)
    | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
}

type RecognitionCtor = new () => SpeechRecognitionLike;

export function getSpeechRecognition(): RecognitionCtor | null {
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}
