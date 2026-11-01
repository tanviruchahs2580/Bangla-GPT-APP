// machine-readable API error codes -> localized, human copy.
// The backend now emits `detail: {code, message}` on new endpoints; legacy
// string details still map through the table where possible.
// copy now flows through i18n so the English UI gets English errors;
// the legacy Bengali detail strings remain the matching key for old payloads.

import { t } from "./i18n";

export type ErrorCopy = {
  text: string;
  action?: "resend-verification" | "retry" | "mfa";
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
  // F-015: a request that never answered (client-side timeout) surfaces with
  // its own machine code and its own copy, because "check your connection" is
  // wrong advice when the connection is fine and the server is not answering.
  timeout: "errTimeout",
  // Login-path failures that previously fell through to the generic copy:
  // MFA step-up (backend 202 token_type=mfa), dead/stale API origins
  // (Vercel edge 503 api_origin_unconfigured, Cloudflare 502 HTML pages),
  // post-login session verification, and native APK misconfiguration.
  mfa_required: "errMfaRequired",
  bad_mfa_code: "errBadMfaCode",
  bad_mfa_token: "errBadMfaToken",
  // A dead or unconfigured API origin is NOT a busy server: it will not
  // recover on its own, so it gets its own copy instead of "busy, try again".
  //
  // The two codes are one outage apart and must not share a sentence.
  // `api_origin_unconfigured` (edge 503) means this deployment was never
  // pointed at a backend — a build/configuration fault. `api_origin_unreachable`
  // (edge 502) means the configured backend is down right now: on 2026-10-26
  // the ephemeral API origin died overnight, every public /api call 502'd, and
  // the single "app isn't connected to a backend yet" string sent the operator
  // looking at the Android client instead of at the dead origin. The
  // unreachable case now says the service is down and that it is not the
  // device, which is what the edge itself reports ("an upstream outage, not a
  // client error").
  api_origin_unconfigured: "errApiOriginDown",
  api_origin_unreachable: "errApiOriginUnreachable",
  // The edge proxy's deadline fired (connect held open, no response):
  // transient by nature, so it reads as the retryable timeout, not as an
  // outage the user cannot act on.
  api_origin_timeout: "errTimeout",
  bad_gateway: "errServiceUnavailable",
  service_unavailable: "errServiceUnavailable",
  revocation_unavailable: "errServiceUnavailable",
  verify_failed: "errVerifyFailed",
  api_base_unconfigured: "errApiUnconfigured",
  // A photo the server could not decode or re-encode. Distinct from the
  // client-side size/type checks (which answer before the upload): this
  // one means the file itself was unusable, so the advice is a different
  // photo, not a smaller one. image_type_mismatch is the same verdict from
  // the magic-byte sniff (S-011), and it reached the UI as the generic copy
  // because only image_invalid was listed.
  image_invalid: "errImageInvalid",
  image_type_mismatch: "errImageInvalid",
  // 503: the sanitizer's Pillow is missing -- a deployment fault, not the
  // student's photo, so it gets the retryable service copy.
  image_support_unavailable: "errServiceUnavailable",
  // Codes the API-wide envelope pass introduced for flows the UI already
  // distinguishes (previously bare strings that fell through to the generic
  // copy): change-password, MFA settings, parent linking, last-admin guard.
  bad_current_password: "errBadCurrentPassword",
  mfa_already_enabled: "errMfaAlreadyEnabled",
  mfa_not_enabled: "errMfaNotEnabled",
  already_linked: "errAlreadyLinked",
  last_admin_guard: "errLastAdmin",
  // 403 from the API when the session must change its password before any
  // other route will answer; the app routes this to the change screen, this
  // copy covers any surface that shows it inline.
  password_change_required: "errPasswordChangeRequired",
  // F-111: the remaining codes the API can emit. The parity guard
  // (src/test/errorCodeParity.test.ts) reads every `code` literal under
  // apps/api/src/bangla_gpt_api and fails when one is missing here, so a new
  // endpoint cannot fall through to the generic sentence unnamed.
  //
  // Codes a student or teacher can act on get their own sentence:
  chapter_not_found: "errChapterNotFound",
  subject_not_found: "errSubjectNotFound",
  attempt_not_found: "errAttemptNotFound",
  assignment_not_found: "errAssignmentNotFound",
  student_not_found: "errStudentNotFound",
  empty_roster: "errEmptyRoster",
  students_only: "errStudentsOnly",
  unsafe_content: "errUnsafeContent",
  consent_not_accepted: "errConsentRequired",
  guardian_consent_required: "errGuardianConsentRequired",
  class_level_required: "errClassLevelRequired",
  password_too_common: "errPasswordTooCommon",
  password_too_short: "errPasswordTooShort",
  password_unchanged: "errPasswordUnchanged",
  mfa_locked: "errMfaLocked",
  no_graded_data: "errNoGradedData",
  mixed_class_levels: "errMixedClassLevels",
  empty_query: "errEmptyQuery",
  import_empty: "errImportEmpty",
  import_too_large: "errImportTooLarge",
  not_linked: "errNotLinked",
  direct_link_disabled: "errDirectLinkDisabled",
  session_ended: "errSessionExpired",
  session_expired: "errSessionExpired",
  // Generation is off until the index, the budget or the provider recovers;
  // the retryable "answers are not being generated" copy is the honest one.
  index_unavailable: "errLlmUnavailable",
  ai_budget_exceeded: "errLlmUnavailable",
  provider_unavailable: "errLlmUnavailable",
  // Deployment faults behind a service that is expected back.
  database_unavailable: "errServiceUnavailable",
  provider_misconfigured: "errServiceUnavailable",
  provider_unconfigured: "errServiceUnavailable",
  renew_unavailable: "errServiceUnavailable",
  pii_key_unconfigured: "errServiceUnavailable",
  // Permission and ownership refusals with no more specific surface copy.
  other_school: "errNotAllowed",
  content_read_only: "errNotAllowed",
  impersonation_forbidden: "errNotAllowed",
  not_impersonation: "errNotAllowed",
  session_not_bindable: "errNotAllowed",
  metrics_denied: "errNotAllowed",
  no_student_profile: "errNotAllowed",
  staff_cannot_submit_student_quiz: "errNotAllowed",
  // An expired or wrong invite code is exactly the invite sentence.
  invite_expired: "errInvalidInvite",
  invalid_code: "errInvalidInvite",
  // Plumbing and validation codes that surface only under their owning
  // screen's own handling; the generic retry sentence is deliberate. Checked
  // so a rename upstream fails the parity guard instead of silently
  // re-falling through.
  already_used: "errGeneric",
  classroom_exists: "errGeneric",
  classroom_not_found: "errGeneric",
  code_used: "errGeneric",
  content_not_found: "errGeneric",
  conversation_not_found: "errGeneric",
  document_not_found: "errGeneric",
  feedback_not_found: "errGeneric",
  internal_error: "errGeneric",
  invalid_explanation_style: "errGeneric",
  invalid_idempotency_key: "errGeneric",
  invalid_kind: "errGeneric",
  invalid_payload: "errGeneric",
  invalid_subject_focus: "errGeneric",
  invite_not_found: "errGeneric",
  job_not_found: "errGeneric",
  missing_target: "errGeneric",
  no_replacement: "errGeneric",
  no_school: "errGeneric",
  not_found: "errGeneric",
  not_owner: "errGeneric",
  not_revocable: "errGeneric",
  note_not_found: "errGeneric",
  notification_not_found: "errGeneric",
  paper_finalised: "errGeneric",
  pdf_unsupported: "errGeneric",
  pii_review_failed: "errGeneric",
  purge_confirmation_required: "errGeneric",
  qpaper_not_found: "errGeneric",
  review_required: "errGeneric",
  school_not_found: "errGeneric",
  target_not_found: "errGeneric",
  unknown_kind: "errGeneric",
  unknown_learning_pref: "errGeneric",
  unknown_question_ref: "errGeneric",
  unknown_student: "errGeneric",
  user_not_found: "errGeneric",
};

const ACTION: Record<string, ErrorCopy["action"]> = {
  email_unverified: "resend-verification",
  mfa_required: "mfa",
  bad_mfa_code: "mfa",
  llm_unavailable: "retry",
  tutor_unavailable: "retry",
  network: "retry",
  timeout: "retry",
  bad_gateway: "retry",
  service_unavailable: "retry",
  api_origin_unconfigured: "retry",
  api_origin_unreachable: "retry",
  api_origin_timeout: "retry",
  image_invalid: "retry",
  image_type_mismatch: "retry",
  revocation_unavailable: "retry",
  verify_failed: "retry",
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

/**
 * The machine code inside whatever shape the API sent.
 *
 * FastAPI wraps errors as `{detail: {code, message}}`, the Vercel edge proxy
 * answers flat `{code, message}`, and old endpoints sent a bare Bengali
 * string. Every page-level catcher passes the raw body here, so without
 * unwrapping `detail` a coded FastAPI error (image_invalid, rate_limited,
 * llm_unavailable, …) matched nothing and every surface showed the generic
 * "something went wrong" — found by driving the tutor's corrupted-image case,
 * which the API answers with 422 image_invalid and the UI answered generically.
 * Unwrapping in this one place reaches the legacy string map too, which had
 * the same problem for the same reason.
 */
function codeOf(detail: unknown): string | undefined {
  const body =
    detail && typeof detail === "object" && "detail" in detail
      ? (detail as { detail?: unknown }).detail
      : detail;
  if (body && typeof body === "object") {
    return (body as { code?: string }).code;
  }
  if (typeof body === "string") {
    // A bare machine code, which is what the register / verify / reset paths
    // hold: they read `err.code` and pass the string on. The string branch used
    // to consult LEGACY_BN only, so `friendlyError("rate_limited")` and
    // `friendlyError("invalid_token")` fell through to the generic copy even
    // though KEY maps both -- a student who hit the login rate limit while
    // registering was told "something went wrong" instead of "too many
    // attempts, wait a minute". Accepting either shape here fixes every caller
    // at once rather than one screen at a time.
    return KEY[body] ? body : LEGACY_BN[body];
  }
  return undefined;
}

export function friendlyError(detail: unknown): ErrorCopy {
  const code = codeOf(detail);
  if (code && KEY[code]) {
    return { text: t(KEY[code]), action: ACTION[code] };
  }
  return { text: t("errGeneric"), action: "retry" };
}
