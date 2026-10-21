# Bangla terminology glossary (single source of truth)

Status of this document: **prescriptive**. It records the terms the product has
decided to use, and the forms that must not come back. `scripts/check_glossary.py`
reads the table below and fails when an `avoid` form appears in the Bangla UI
dictionary (`apps/web/src/i18n.ts`).

It is **not** a certification of language quality. Terms are reviewed by a
native speaker through `docs/native-review-sheet.md`; an open disagreement
belongs in the `Open decisions` section below, not in a silent edit.

## How to change a term

1. Find the term here. If it is missing, add a row with the English concept, the
   approved Bangla form and the forms to avoid.
2. Change the copy in `apps/web/src/i18n.ts` (both dictionaries stay in sync).
3. Run `python scripts/check_glossary.py` — it must pass.
4. Record the decision in `docs/native-review-sheet.md` (reviewer, date, note).

Two rules for the table:

- An `avoid` form must never be a substring of the approved form, or the check
  would flag the approved text itself. The script refuses to run in that case.
- Field spacing inside a term is significant: `পাঠ্য বই` and `পাঠ্যবই` are
  different strings to the checker, which is exactly the class of drift it
  exists to catch.

## Terms

| English | approved | avoid | dictionary keys |
|---|---|---|---|
| worksheet | ওয়ার্কশীট | ওয়ার্কশিট | genWorksheet |
| answer key | উত্তরমালা | উত্তর মালা | genAnswerKey |
| homework | হোমওয়ার্ক | হোম ওয়ার্ক | genHomework |
| rubric | রুব্রিক | রুব্রিক্স | genRubric |
| lesson plan | লেসন প্ল্যান | লেসন প্লান | genLessonPlan |
| question paper | প্রশ্নপত্র | প্রশ্ন পত্র, প্রশ্ন-পত্র | qpTitle |
| quiz | কুইজ | | quizTitle |
| short test | সংক্ষিপ্ত পরীক্ষা | | stTitle, asmTabShortTests |
| chapter | অধ্যায় | | chapter |
| subject | বিষয় | | subject |
| class, grade | শ্রেণি | শ্রেনি, শ্রেণী | classLabel |
| student | শিক্ষার্থী | | roleStudent |
| teacher | শিক্ষক | | roleTeacher |
| guardian, parent | অভিভাবক | | roleParent |
| administrator | অ্যাডমিন | এডমিন | roleAdmin |
| school administrator | স্কুল অ্যাডমিন | স্কুল এডমিন | roleSchoolAdmin |
| AI tutor | AI টিউটর | এআই টিউটর | aiTutor |
| practice | অনুশীলন | | practice |
| progress | অগ্রগতি | প্রগ্রেস | progressTitle |
| textbook | পাঠ্যবই | পাঠ্য বই | textbookLabel, trustNctb |
| marks | নম্বর | মার্কস | qpMarks |
| duration | সময় | ডিউরেশন | qpDuration |
| notification | নোটিফিকেশন | নোটিফীকেশন | notifications |
| AI memory | AI মেমোরি | AI মেমরি | aiMemoryPanel |
| consent | সম্মতি | সম্মতী | consentPrefix |
| offline copy | অফলাইন কপি | | offlineBadge |
| weak chapter | দুর্বল অধ্যায় | দূর্বল অধ্যায় | weakChapters |

Notes on evidence:

- `শ্রেনি` / `শ্রেণী` were corrected to the NCTB (Bangladesh Academy) spelling
  `শ্রেণি` in `33b3ecf fix(i18n): Bangladesh Academy-standard Bangla` (v0.6.1).
  `apps/api/src/bangla_gpt_api/nctb/normalize.py` deliberately still maps the
  older corpus spelling `শ্রেণী` to the canonical form — that is ingestion, not
  UI copy, so the check does not scan it.
- `লেসন প্ল্যান`, `ওয়ার্কশীট`, `হোমওয়ার্ক`, `রুব্রিক`, `উত্তরমালা` are the
  loanword set chosen by the owner in the same release; the native forms are
  listed under Open decisions rather than treated as errors.
- `AI ক্লাসরুম ইন্টেলিজেন্স` (key `anaCiTitle`) keeps the loanword `ক্লাসরুম`
  because it is a product label for teachers; elsewhere classrooms are
  `শ্রেণি` / `শ্রেণিসমূহ`. This is a recorded exception, not a precedent.

## Open decisions (needs a native speaker)

These are real inconsistencies found while building the glossary. They are
listed here, and reported by the check as `pending` (a warning, not a failure)
until the reviewer decides.

| Concept | In use today | Where |
|---|---|---|
| lesson plan | লেসন প্ল্যান (Create hub) vs পাঠ পরিকল্পনা (Create page) | `genLessonPlan`, `lpTitle`, `lpChapterLabel`, `lpGenerate` |
| short test | সংক্ষিপ্ত পরীক্ষা (title) vs ছোট পরীক্ষা (assignment copy) | `stTitle`, `assignedShortTest`, `notifShorttestAssigned` |
| student | শিক্ষার্থী (default) vs ছাত্রছাত্রী (natural plural) | `roleStudent` and marketing copy |
| teacher | শিক্ষক (default) vs টিচার (colloquial) | `roleTeacher` |
| guardian | অভিভাবক (default) vs প্যারেন্ট | `roleParent` |
