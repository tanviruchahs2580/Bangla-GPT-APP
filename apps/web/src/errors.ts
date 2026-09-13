// B8: machine-readable API error codes -> localized, human copy.
// The backend now emits `detail: {code, message}` on new endpoints; legacy
// string details still map through the table where possible.
// RENO: copy now flows through i18n so the English UI gets English errors;
// the legacy Bengali detail strings remain the matching key for old payloads.

import { t } from "./i18n";

export type ErrorCopy = {
  text: string;
  action?: "resend-verification" | "retry";
};

const KEY: Record<string, Parameters<typeof t>[0]> = {
  bad_credentials: "errBadCredentials",
  email_taken: "errEmailTaken",
  email_unverified: "errEmailUnverified",
  rate_limited: "errRateLimited",
  no_quiz_for_filter: "errNoQuiz",
  answer_count_mismatch: "errAnswerCount",
  attempt_already_graded: "errAlreadyGraded",
  invalid_invite: "errInvalidInvite",
  invalid_token: "errInvalidToken",
  llm_unavailable: "errLlmUnavailable",
  tutor_unavailable: "errTutorUnavailable",
  not_allowed: "errNotAllowed",
  insufficient_role: "errNotAllowed",
  network: "errNetwork",
};

const ACTION: Record<string, ErrorCopy["action"]> = {
  email_unverified: "resend-verification",
  llm_unavailable: "retry",
  tutor_unavailable: "retry",
  network: "retry",
};

// Legacy string details the backend used to send verbatim (Bengali).
const LEGACY_BN: Record<string, string> = {
  "ইমেইল বা পাসওয়ার্ড সঠিক নয়।": "bad_credentials",
  "এই ইমেইল দিয়ে আগেই অ্যাকাউন্ট খোলা আছে।": "email_taken",
  "আগে ইমেইল যাচাই করুন — কোড পাঠানো হয়েছে।": "email_unverified",
  "অনেকবার চেষ্টা হয়েছে। এক মিনিট অপেক্ষা করুন।": "rate_limited",
  "এই শ্রেণি/বিষয়ে এখনো কুইজ তৈরি হয়নি।": "no_quiz_for_filter",
  "উত্তরের সংখ্যা মিলছে না। আবার জমা দিন।": "answer_count_mismatch",
  "এই কুইজ আগেই জমা হয়ে গেছে।": "attempt_already_graded",
  "ইনভাইট কোডটি ভুল বা মেয়াদ শেষ।": "invalid_invite",
  "কোডটি ভুল বা মেয়াদ শেষ।": "invalid_token",
  "এখন উত্তর তৈরি হচ্ছে না — একটু পরে আবার চেষ্টা করুন।": "llm_unavailable",
  "টিউটর সেবা এখন বন্ধ — একটু পরে চেষ্টা করুন।": "tutor_unavailable",
  "এটি করার অনুমতি নেই।": "not_allowed",
  "ইন্টারনেট সংযোগ পরীক্ষা করুন।": "network",
};

export function friendlyError(detail: unknown): ErrorCopy {
  let code: string | undefined;
  if (detail && typeof detail === "object") {
    code = (detail as { code?: string }).code;
  }
  if (!code && typeof detail === "string") {
    code = LEGACY_BN[detail];
  }
  if (code && KEY[code]) {
    return { text: t(KEY[code]), action: ACTION[code] };
  }
  return { text: t("errGeneric"), action: "retry" };
}
