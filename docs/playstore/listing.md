# Play Store listing copy

Two reviewed copies — `bn-BD` (default locale) and `en-US` — plus the asset
manifest. Character budgets are Play's: app name ≤ 30, short description ≤ 80,
full description ≤ 4000.

Everything below is a claim the app must actually support. The grounding rule is
the audit's: a store listing is user-visible copy, so "answers cite their
sources" is only writable because the tutor's answer contract requires citations
and the coverage gate abstains instead of guessing.

## bn-BD (default)

**অ্যাপের নাম (≤30):** `বাংলা GPT টিউটর` (13 characters)

**সংক্ষিপ্ত বিবরণ (≤80):**
`শ্রেণি ৬-১০ · পাঠ্যবইভিত্তিক উত্তর, সূত্রসহ`

**পূর্ণ বিবরণ:**

```text
বাংলা GPT টিউটর — ষষ্ঠ থেকে দশম শ্রেণির পাঠ্যবইভিত্তিক পড়াশোনার সহায়ক।

যা করে:
• প্রশ্ন লিখুন বা ছবি তুলে পাঠান — উত্তর আসে পাঠ্যবইয়ের অংশ থেকে, সাথে সূত্র দেখানো হয়
• প্রতিটি উত্তরের নিচে সূত্র থাকে; পাঠ্যবইয়ে উত্তর না থাকলে অনুমান না করে "জানি না" বলতে পারে
• অনুশীলনী, কুইজ ও অগ্রগতির হিসাব
• শিক্ষকের জন্য ক্লাসরুম, প্রশ্নপত্র ও কনটেন্ট তৈরি
• অভিভাবকের জন্য সন্তানের অগ্রগতির সারসংক্ষেপ

যা নয়:
• এটি পাঠ্যবই বা শিক্ষকের বিকল্প নয়
• ব্যক্তিগত তথ্য (নাম, ফোন, ঠিকানা) চাওয়া হয় না — শুধু পড়াশোনার প্রশ্ন

গোপনীয়তা: https://<your-web-host>/privacy
শর্তাবলি: https://<your-web-host>/terms

এআই-নির্ধারিত উত্তর ভুল হতে পারে। গুরুত্বপূর্ণ ক্ষেত্রে শিক্ষকের সাথে মিলিয়ে নিন।
```text

> **Native review gate.** The Bengali copy above is engineering-written and is
> marked **NEEDS NATIVE REVIEW** by the repo's own rule
> (`docs/native-review-sheet.md`): a Bangla-native reviewer must approve it (and
> the in-app strings it mirrors) before upload. Track it on the same review
> sheet as the UI copy; the listing is user-visible text like any other.

## en-US

**App name (≤30):** `Bangla GPT Tutor`

**Short description (≤80):**
`Homework help grounded in the NCTB textbooks, with the source shown`

**Full description:**

```text
Bangla GPT Tutor helps students in classes 6-10 study from their own textbooks.

What it does:
• Ask by typing or by photo of the question
• Answers are built from textbook passages and show their sources
• Refuses instead of guessing when the textbook does not cover the question
• Practice sets, quizzes and progress tracking
• Teachers get classrooms, question papers and content tools
• Parents get a progress summary

What it is not:
• Not a replacement for a textbook or a teacher
• No personal details are required - just the study question

Privacy: https://<your-web-host>/privacy
Terms: https://<your-web-host>/terms

AI answers can be wrong. Check anything important with a teacher.
```

## Assets

| Asset | Requirement | Source |
|---|---|---|
| App icon | 512×512 px, 32-bit PNG with alpha | `apps/web/public/icon-512.png` |
| Feature graphic | 1024×500 px, JPEG or 24-bit PNG, no alpha | `docs/playstore/assets/screenshots/feature-graphic.jpg` |
| Phone screenshots | 2–8 images, sides 320–3840 px, aspect 9:16–16:9, 24-bit, no alpha | `docs/playstore/assets/screenshots/*.jpg` |
| Tablet screenshots | Optional; required only if you want the tablet listing | not generated (the layout is a responsive web view) |

Regenerate the screenshots after any UI change:

```bash
cd apps/web
STORE_ASSETS=1 npx playwright test e2e/store-listing.spec.ts
```

The spec renders the real app through the seeded e2e accounts and writes
`captions.json` beside the images, so the listing copy above and the captured
screens cannot drift silently.

## Category and contact

- Category: **Education**
- Tags: study help, exam preparation, tutoring
- Contact email: a monitored address you control (Play shows it publicly)
- Website: `https://<your-web-host>`

## Review notes for the Play reviewer (Console → App content → App access)

Answers to the two questions that decide whether a reviewer can use the app:

1. **Does any part of the app require login?** Yes — open `/login`. Provide the
   demo credentials below (create them on the deployed environment, then change
   the password after review).
2. **Is there a second role behind the login?** Yes — teacher and parent areas;
   one demo student account is enough for review, and the reviewer can browse the
   public pages without an account.

```text
Student demo:  DEMO_STUDENT_EMAIL / DEMO_STUDENT_PASSWORD
Teacher demo:  DEMO_TEACHER_EMAIL / DEMO_TEACHER_PASSWORD
```

Do not commit real credentials here or anywhere else in the repository: create
the demo accounts on the deployed API and paste them into the Play Console form.

## ASO notes

- The primary search intent for this market is Bangla: "নার্সারি থেকে দশম শ্রেণির
  পড়া", "প্রশ্ন উত্তর", "পাঠ্যবই" — the bn-BD copy leads with the class range and
  the grounded-answer promise because those are the two things that distinguish
  this app from a generic chatbot listing.
- Screenshot captions are baked into the images; keep them short enough to read
  at thumbnail size.
