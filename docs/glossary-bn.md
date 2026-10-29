# Bangla terminology glossary (proposal)

Status: **proposal for review, not an approved glossary.** Canonical terms below
are one reviewer's best judgement in standard Bangladeshi চলিত register, based
on the measured variants in `.qa-work/audit/I18N/report.md` (audit run
2026-10-29) and the strings' `file:line`. A native-speaker reviewer (the
language-review role on `docs/LAUNCH_READINESS_CHECKLIST.md`) and the project
owner must confirm them; every row marked "flagged" needs that confirmation
before it becomes binding. Until then the existing copy stands.

Purpose: one concept, one Bangla word, everywhere a student or guardian can see
it (UI, PDF, email). The review record's term table
(`docs/native-review-sheet.md:36-44`) is empty today; when terms are approved,
record them there and have the sheet reference this file. The generator that
builds the review sheet already points reviewers at "the glossary"
(`scripts/gen_native_review.py:23`).

## Recommended terms

| Concept | Canonical term | Variants shipping now | Rationale | Confirmation |
|---|---|---|---|---|
| worksheet | ওয়ার্কশীট | ওয়ার্কশীট only (`i18n.ts:22,51`) | transliteration is the Bangladeshi classroom norm; no native alternative in use | certain |
| answer key | উত্তরমালা | উত্তরমালা only (`i18n.ts:52,58`; `services/qp_pdf.py:50,88,97`) | single term already; no change needed | certain |
| homework | বাড়ির কাজ | হোমওয়ার্ক (`i18n.ts:53`; `providers/mock.py:273`) vs বাড়ির কাজ (`i18n.ts:298`) | native and unambiguous for student copy; keep হোমওয়ার্ক only if a textbook uses it | flagged for linguist |
| rubric | রুব্রিক | রুব্রিক (`i18n.ts:54`); মানদণ্ড unused | term is established in NCTB teacher training; a native coinage was never adopted | flagged for linguist |
| lesson plan | পাঠ পরিকল্পনা | লেসন প্ল্যান (`i18n.ts:22,55`) vs পাঠ পরিকল্পনা (`i18n.ts:282-284`) | native, unambiguous, already used on the surfaces teachers read most | flagged for linguist |
| save | সেভ করুন (action) / সংরক্ষিত (state) | সেভ (`i18n.ts:43,44,67,126`) vs সংরক্ষণ/সংরক্ষিত (`i18n.ts:45,47,98,108`) | one action word and one state word, applied consistently; transliteration matches button-convention | flagged for linguist |
| delete | মুছুন | মুছুন / মুছে ফেলুন (11 strings, `i18n.ts:48,72,107,172,173,231-234,372`) vs অপসারণ (`pages/LegalPage.tsx:29`) | মুছুন for destructive buttons; অপসারণ only in legal prose as found | certain |
| score | নম্বর (marks on a paper) / স্কোর (quiz result) | স্কোর (`i18n.ts:123,223,441`) vs নম্বর (`i18n.ts:113,261`; `qp_pdf.py:53`) | both are correct in different domains; split by domain instead of banning one | flagged for linguist |
| revision | পুনরালোচনা | রিভিশন (`i18n.ts:182,183`) vs পুনরালোচনা (`i18n.ts:615`) | native word; রিভিশন is an English transliteration | flagged for linguist |
| grounded / sourced | প্রমাণ (evidence panel), পাঠ্যবই-সমর্থিত (answer badge), সূত্রসহ/সূত্রবিহীন (source counters) | সূত্রসহ/সূত্রবিহীন (`i18n.ts:131,132`), প্রমাণ (`:161,217`), সমর্থিত (`:216`), উৎস (`:71`) | distinct jobs need distinct words; ban সমর্থিত and উৎস for the badge so the badge reads one way | flagged for linguist |
| quiz | কুইজ | কুইজ throughout (`i18n.ts:17,140,167,218` and later); no competitor found | established loanword in BD classrooms | certain |
| chapter | অধ্যায় | অধ্যায় (`i18n.ts:18,36,180`); no competitor found | curriculum-standard term | certain |
| class / grade | শ্রেণি (class) ; গ্রেড kept only for grading (গ্রেড করা) | শ্রেণি everywhere (`i18n.ts:73,203,251,344,389`); গ্রেড in "গ্রেড করা কুইজ" (`i18n.ts:222,304`) | one noun for a class, grading stays an adjective-verb; school is স্কুল in chrome (বিদ্যালয় only in official text — flagged) | certain for শ্রেণি; school choice flagged |
| teacher | শিক্ষক | শিক্ষক (`i18n.ts:21,251,352`); no competitor found | standard term, no change | certain |
| student | শিক্ষার্থী | শিক্ষার্থী (`i18n.ts:204,252,314,363`); শিক্ষার্থীবৃন্দ in one label (`:253`) | standard and already dominant; ছাত্র avoided (gendered/narrower) | certain |
| guardian | অভিভাবক | অভিভাবক (`i18n.ts:14,40,239,364,395-397`); no competitor found | standard legal and everyday term | certain |
| notice | নোটিফিকেশন (in-app feed, as shipped) | নোটিফিকেশন only (`i18n.ts:33,34`) | keep the shipped word for the feed; reserve বিজ্ঞপ্তি for official school announcements if that feature is added | flagged for linguist |
| dashboard | ড্যাশবোর্ড | ড্যাশবোর্ড (`i18n.ts:251,351,364,369,500`) | transliteration is the accepted register for software surfaces; no native term in use | certain |

## Numeral policy (proposal; current state is inconsistent)

Measured inconsistency (F-I18N-6): static copy uses Bangla digits in prose
(`i18n.ts:25,27,29,85,345,353,388,389,523,676`) while every interpolated number
is rendered in Latin digits by `String(v)` (`i18n.ts:1385-1394`, 39 keys) — for
example `miniQuiz` shows "(৩টি প্রশ্ন)" beside `activityQuestions` "{n}টি প্রশ্ন".
No numeral policy document exists in the repository.

Proposal, to be confirmed by the owner and the language reviewer:

1. Bangla numerals (০-৯) for counts and quantities inside Bangla prose that a
   student, teacher or guardian reads: "৩টি প্রশ্ন", "২য় অধ্যায়".
2. Latin numerals for mathematical and scientific expressions (equations,
   formulas, units), machine values (scores as computed numbers if displayed
   alongside charts, IDs, codes), phone numbers, URLs and email addresses.
   The corpus already mixes these by convention: "৩x + ৫" beside "b² − ৪ac"
   is a legitimate Bangla-medium mix, while the second is internally
   inconsistent (`.qa-work/audit/I18N/report.md`, flagged section).
3. Apply the conversion at one formatting boundary (the translation helper and
   the PDF/email renderers), never in stored data or API payloads.
4. Error codes, HTTP values and technical diagnostics stay Latin regardless.

Flagged for the owner: whether emails and generated PDFs follow the same rule
as the UI, and whether the currency figure in `docs/capacity_plan.md` stays
Bangla-digit (it is a business number, not user copy).

## How to use this document

- New copy uses the canonical term for the concept; a genuinely new synonym
  goes through this file first, not into a string.
- Enforcement today is review-only; a banned-variant check per concept
  (suggested guard in F-I18N-4, e.g. extending `scripts/check_i18n.py`) is not
  implemented.
- Approved decisions move to `docs/native-review-sheet.md` (owner action; this
  document cannot edit that file in the current change set).
