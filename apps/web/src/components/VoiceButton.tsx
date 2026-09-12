import { useEffect, useRef, useState } from "react";
import { Mic } from "lucide-react";
import { t } from "../i18n";
import { getSpeechRecognition, type SpeechRecognitionLike } from "../lib/voice";

/**
 * S1.12: mic button for the tutor composer. Hidden entirely when the browser
 * has no Speech Recognition; recognition errors just stop recording so the
 * manual composer always keeps working.
 */
export function VoiceButton({
  onTranscript,
}: {
  onTranscript: (text: string) => void;
}) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const supported = getSpeechRecognition() !== null;

  useEffect(() => {
    return () => {
      recRef.current?.abort();
      recRef.current = null;
    };
  }, []);

  if (!supported) return null;

  const toggle = () => {
    if (listening) {
      recRef.current?.stop();
      setListening(false);
      return;
    }
    const Ctor = getSpeechRecognition();
    if (!Ctor) return;
    const rec = new Ctor();
    rec.lang = "bn-BD";
    rec.continuous = false;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      const said = e.results[0]?.[0]?.transcript?.trim();
      if (said) onTranscript(said);
    };
    rec.onerror = () => {
      /* denied mic / no-speech / unsupported locale: drop silently */
      setListening(false);
    };
    rec.onend = () => setListening(false);
    recRef.current = rec;
    try {
      rec.start();
      setListening(true);
    } catch {
      setListening(false);
    }
  };

  return (
    <button
      type="button"
      className={
        listening ? "icon-btn voice-btn voice-live" : "icon-btn voice-btn"
      }
      aria-label={t("voiceMic")}
      aria-pressed={listening}
      onClick={toggle}
    >
      <Mic size={18} aria-hidden />
    </button>
  );
}
