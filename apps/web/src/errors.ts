// B8: machine-readable API error codes -> localized, human copy.
// The backend now emits `detail: {code, message}` on new endpoints; legacy
// string details still map through the table where possible.

export type ErrorCopy = { text: string; action?: 'resend-verification' | 'retry' }

const BN: Record<string, ErrorCopy> = {
  bad_credentials: { text: 'ইমেইল বা পাসওয়ার্ড সঠিক নয়।' },
  email_taken: { text: 'এই ইমেইল দিয়ে আগেই অ্যাকাউন্ট খোলা আছে।' },
  email_unverified: {
    text: 'আগে ইমেইল যাচাই করুন — কোড পাঠানো হয়েছে।',
    action: 'resend-verification',
  },
  rate_limited: { text: 'অনেকবার চেষ্টা হয়েছে। এক মিনিট অপেক্ষা করুন।' },
  no_quiz_for_filter: { text: 'এই শ্রেণি/বিষয়ে এখনো কুইজ তৈরি হয়নি।' },
  answer_count_mismatch: { text: 'উত্তরের সংখ্যা মিলছে না। আবার জমা দিন।' },
  attempt_already_graded: { text: 'এই কুইজ আগেই জমা হয়ে গেছে।' },
  invalid_invite: { text: 'ইনভাইট কোডটি ভুল বা মেয়াদ শেষ।' },
  invalid_token: { text: 'কোডটি ভুল বা মেয়াদ শেষ।' },
  llm_unavailable: { text: 'এখন উত্তর তৈরি হচ্ছে না — একটু পরে আবার চেষ্টা করুন।', action: 'retry' },
  tutor_unavailable: { text: 'টিউটর সেবা এখন বন্ধ — একটু পরে চেষ্টা করুন।', action: 'retry' },
  not_allowed: { text: 'এটি করার অনুমতি নেই।' },
  insufficient_role: { text: 'এটি করার অনুমতি নেই।' },
  network: { text: 'ইন্টারনেট সংযোগ পরীক্ষা করুন।', action: 'retry' },
}

export function friendlyError(detail: unknown): ErrorCopy {
  if (detail && typeof detail === 'object') {
    const code = (detail as { code?: string }).code
    if (code && BN[code]) return BN[code]
  }
  if (typeof detail === 'string') {
    const hit = Object.values(BN).find((v) => v.text === detail)
    if (hit) return hit
  }
  return { text: 'কিছু একটা সমস্যা হয়েছে। একটু পরে আবার চেষ্টা করুন।', action: 'retry' }
}
