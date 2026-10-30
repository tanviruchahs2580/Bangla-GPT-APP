# Bangla terminology, register and numeral policy

This document is the binding copy reference for the product. It was a proposal
in the 2026-10-29 audit (`F-I18N-4`); the wave-2 language pass applied it and
the markers below now read **adopted**. The applied scope is recorded per term
so a later string cannot silently reintroduce a competing variant. Rows still
marked **flagged** need the owner or a native-speaker reviewer; until then the
shipped wording stands.

Terminology in a curriculum product is not a style choice: the same concept
must use the same word everywhere a student, teacher or guardian can see it.
Every decision here is standard Bangladeshi চলিত Bangla. Where the reviewer was
not certain, the string was left alone and listed under "Left for the linguist"
instead of guessed.

Related records: `docs/native-review/ui-strings.md` (generated collection of
every user-facing Bangla string) and `docs/native-review-sheet.md` (the review
record; its decision and term tables must be updated to point here — owner
action, see "Handoff" at the end).

## Terms: adopted

| Concept | Canonical term | Applied scope (wave-2) | Rationale |
|---|---|---|---|
| worksheet | ওয়ার্কশীট | UI (`i18n.ts` featTeacherSub, genWorksheet) | transliteration is the Bangladeshi classroom norm; no native alternative in use |
| answer key | উত্তরমালা | UI (genAnswerKey) and PDF (`services/qp_pdf.py`) | single term already; unchanged |
| homework | বাড়ির কাজ | UI `genHomework`; API mock provider still says হোমওয়ার্ক (handoff) | native and unambiguous for student copy; matches `lpSecHomework`, which already said বাড়ির কাজ |
| rubric | রুব্রিক | UI (genRubric) | established in NCTB teacher training; a native coinage was never adopted |
| lesson plan | পাঠ পরিকল্পনা | UI (`featTeacherSub`, `genLessonPlan`, `lpTitle`, `lpChapterLabel`, `lpGenerate`) | native, unambiguous, already used on the surfaces teachers read most; লেসন প্ল্যান retired |
| save | সেভ করুন (action) / সংরক্ষিত (state) | UI: `save`, `saveAsNote` (action); `noteSaved`, `genLibrary`, `savedNotesTitle`, `prefsSaved`, `downloaded` (state) | one action word and one state word; "সেভ করা ডকুমেন্ট" and "সেভ হয়েছে" were the mixed state forms and are gone |
| delete | মুছুন | UI destructive buttons and labels (`deleteGeneric` → মুছুন, `noteDelete`, `deleteChat`, `deleteAccount`, `clearMemory`, `purgeExpired`); অপসারণ stays in legal prose (`LegalPage.tsx`) as shipped | মুছুন is the everyday imperative; অপসারণ in the privacy text is formal register, which legal copy wants |
| score | নম্বর (marks on a paper) / স্কোর (quiz result) | UI: `qpMarks` নম্বর; `avgScore`, `reportAvg`, `sugg_keep_momentum` স্কোর; PDF `qp_pdf.py` নম্বর | both words are correct in their domain; the split is by domain, not by preference — a paper carries নম্বর, an attempt carries স্কোর |
| revision | পুনরালোচনা | UI `revisionTab`, `revisionEmpty`, `anaCiWeak` | native word; রিভিশন was an English transliteration |
| grounded / sourced | প্রমাণ (evidence panel: `evidenceTitle`), পাঠ্যবই-সমর্থিত (answer badge, positive and negative), সূত্র (counters: `genSourcesCount`, `aiqGrounded`/`aiqUngrounded`, `lowConfidenceHint`) | UI: `unsupportedBadge` moved from প্রমাণ নেই to পাঠ্যবই-সমর্থিত নয়; `genSourcesCount` moved from উৎস to সূত্র | the badge must read as one concept in both states; সূত্র is the citation word, উৎস the data-origin word (below) |
| উৎস vs সূত্র | উৎস = data origin (admin `admSource`); সূত্র = citation / textbook source counter | UI as above | not one concept but two: an ingested version has an origin (উৎস), a grounded answer cites sources (সূত্র) |
| support plan | সহায়তা পরিকল্পনা | UI `spTitle`/`spCreate`/`spEmpty` and `notifSupportPlan` | notifSupportPlan said "সহায়তা প্ল্যান", splitting the same feature name; one term now |
| quiz | কুইজ | UI throughout | established loanword in BD classrooms |
| chapter | অধ্যায় | UI throughout | curriculum-standard term |
| class / grade | শ্রেণি (class); গ্রেড only for grading | UI throughout (`শ্রেণি`, গ্রেড করা কুইজ) | one noun for a class; grading stays an adjective-verb |
| teacher | শিক্ষক | UI throughout | standard term |
| student | শিক্ষার্থী | UI throughout (শিক্ষার্থীবৃন্দ in the roster label) | standard and dominant; ছাত্র avoided (gendered/narrower) |
| guardian | অভিভাবক | UI throughout | standard legal and everyday term |
| notice | নোটিফিকেশন (in-app feed) | UI `notifications`, `notifEmpty` | keep the shipped word for the feed; বিজ্ঞপ্তি reserved for official school announcements if that feature is added |
| dashboard | ড্যাশবোর্ড | UI throughout | accepted register for software surfaces |
| streak | ধারাবাহিকতা | UI `streakLabel`, `activityHint` (স্ট্রিক retired) | the transliteration was the only place the term appeared twice; ধারাবাহিকতা is the standard word |
| AI assistant | AI সহকারী | UI throughout | consistent with `featTeacherTitle`, `anaCapacityHint` |

## Register and pronouns: adopted policy

Policy (removes the same-screen mixes the audit measured on `WelcomePage`,
`QuizPage` and `AITutorPage`):

1. **আপনি / polite (করুন, দেখুন, দিন)** is the register for every string the
   product itself says: navigation, buttons, forms, empty and error states,
   notices, settings, dashboards, legal text, and the teacher, guardian, school
   and admin surfaces. The student practice hub and home are included — they
   are product voice, not the student's voice.
2. **তুমি / informal** appears only where the string is a **student's own
   words**: the tutor prompt chips that insert a first-person request into the
   composer (`suggestTeach`, `suggestSolve`, `suggestQuizMe`, `suggestImage`,
   `imgSolve`, `imgExplain`, `imgCheck`, `imgSteps`) and the AI's own question
   to the learner in a structured answer (`saCheck` "তুমি বুঝেছ?"), which
   mirrors the informal persona the tutor prompt fixes (`services/tutor.py`).
   First-person strings without a pronoun (`reteach` "আমি বুঝিনি") are
   unaffected.
3. **No imperative mix inside one surface.** If a screen shows a chip pair,
   both labels belong to the same voice class; the tutor screen is the one
   place where student-voice chips sit next to product-voice buttons, and the
   boundary is exactly chip = student's words, button = product's words.

Applied in wave 2: `landingHeroSub` (now প্রশ্ন করুন, কুইজ দিন, অগ্রগতি দেখুন),
`weakPracticeHint` (মনোযোগ দিন), `actionPractice` (অনুশীলন করুন) and
`notifSupportPlan` (আপনার) moved to polite; the student-voice chips were left
informal on purpose. `HomePage.tsx`'s literal "আজ কী শিখতে চাও?" is outside
the dictionary and is listed in the handoff.

## Numeral and plural policy: adopted

1. Bangla numerals (০-৯) for counts and quantities inside copy a student,
   teacher or guardian reads: "৫টি প্রশ্ন", "২য় অধ্যায়", "৮৭% নিশ্চিত".
2. Latin numerals for machine values: ids, attempt numbers, invite codes,
   error codes, HTTP values, timestamps, URLs, e-mail addresses and phone
   numbers. Unit symbols stay Latin even beside Bangla quantities
   ("১.৫ MB-এর কম"). Mathematical expressions keep the convention their
   textbook uses ("৩x + ৫").
3. The conversion happens at one boundary — `t()` in `apps/web/src/i18n.ts`
   (`formatNumber` / `toBanglaDigits`) — and never in stored data or API
   payloads. A value that is entirely a number is a quantity; any other
   interpolated string (a name, a code, a pre-formatted date) is opaque and is
   never rewritten. `MACHINE_VALUE_VARS` names the numeric placeholders that
   must stay Latin (`{id}` today).
4. English counted nouns take a singular sentence at 1 through
   `Intl.PluralRules`. The singular strings live in `EN_SINGULAR`
   (`i18n.ts`) rather than in the dictionaries, because Bangla does not inflect
   for number and a twin entry would exist only for key parity.
   `scripts/check_i18n.py` fails when a key that needs a singular form is
   missing from the table, or when the table drifts from the dictionary.
5. The count classifier টি attaches to the numeral ("৫টি প্রশ্ন"); words that
   are separate words keep their space ("৫ জন", "৫ দিন"). The wave-2 pass
   removed the two "{n} টি" forms that broke this.

## Copy defects decided in wave 2 (F-I18N-7)

| Key | Was | Now | Why |
|---|---|---|---|
| `anaCapacityHint` | AI সহকারী হিসেবে আপনার সামর্থ্য বাড়ায় | AI সহকারী আপনার সামর্থ্য বাড়ায় — শিক্ষকের বিকল্প কখনো নয় | the dangling "হিসেবে" made the sentence ungrammatical (calque of "increases your capacity as an assistant") |
| `thWorkloadTitle` | সাশ্রয়ী সময় | সাশ্রয় হওয়া সময় | সাশ্রয়ী means "economical", not "saved" |
| `anaTitle` | ব্যবহারের পরিসংখ্যা | ব্যবহারের পরিসংখ্যান | পরিসংখ্যা is not a word (calque); পরিসংখ্যান is the standard term |
| `cWorksheetSub` | স্টাডি মেটেরিয়াল | পাঠসহায়ক উপকরণ | English calque; native compound is unambiguous for a teacher |
| `impersonate` | সহায়তা যাচাই | সহায়তা সেশনে প্রবেশ করুন | "support check" lost the impersonation meaning; now matches `actingAs` and `exitImpersonation` |
| `thInsightOk` | এই মুহূর্তে কোনো উদ্বেগজনক প্যাটার্ন নেই | শিক্ষার্থীদের মধ্যে এই মুহূর্তে দুশ্চিন্তার কিছু চোখে পড়ছে না | literal calque of "no concerning patterns" |
| `activityHint` | …কুইজ স্ট্রিক ধরে রাখে | …কুইজ করলে ধারাবাহিকতা থাকে | transliteration retired; the sentence now says what keeps the streak alive for a class 6 reader |

## Left for the linguist or owner (do not treat as decided)

- **School naming (F-I18N-6).** The app chrome says স্কুল (colloquial norm) and
  no NCTB-র wording appears in the repository; বিদ্যালয় stays reserved for
  official/legal text until a curriculum reviewer rules. No string changed.
- **"recommendation".** `clsRecommend` says সুপারিশ while `aiSuggestion` and
  `anaCiTop` say পরামর্শ. The audit's terminology table did not cover this
  concept; the reviewer kept both rather than guess which word the owner wants.
- **Corpus numeral mix.** `data/sample_nctb/class10_math.md` writes
  "b² − ৪ac" (Latin base, Bangla index) — a curriculum reviewer should say
  whether the sample corpus follows Bangla-medium digit convention.
- **Currency and prices.** `docs/capacity_plan.md` is a business document; it
  is not user copy and is untouched by this policy.
- **Email and PDF digit script.** The policy above covers the web UI; whether
  generated PDFs and emails follow the same numeral rule is an owner decision
  (the PDF renderer already uses Bangla digits in its fixed labels).

## Handoff (outside this document's change set)

- `docs/native-review-sheet.md`: mirror the adopted terms and the register and
  numeral policies into its decision and term tables, and record the review
  date/reviewer. This document is the source; the sheet is the signature
  record and is an owner/reviewer action per its own header.
- API copy: `providers/mock.py` still says হোমওয়ার্ক; `nctb/normalize.py`
  normalises a শ্রেণী variant to শ্রেণি (correct — recorded here so the pair is
  not mistaken for drift).
- Web literals outside the dictionary: `HomePage.tsx:122` "আজ কী শিখতে চাও?"
  must become "আজ কী শিখতে চান?" to match `whatToDo` (same screen, same
  register).
