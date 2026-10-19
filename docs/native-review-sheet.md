# Native-speaker review sheet

**NEEDS NATIVE REVIEW.** The engineering audit that added this file does not
certify Bangla language quality, curricular correctness or age-appropriateness
of copy (audit protocol T14). It collected the strings and set up the process;
a native speaker and a teacher make the decisions.

## What is here

| File | What it is | Generated? |
|---|---|---|
| `docs/native-review/ui-strings.md` | every user-facing Bangla string with `file:line`, the key, the text and an empty `concern` column | yes, by `scripts/gen_native_review.py` |
| `docs/i18n-glossary.md` | the terminology the product has decided to use, and the forms that must not come back | no, hand-maintained |
| `scripts/check_glossary.py` | fails when an `avoid` form reappears in the UI dictionary | n/a |

Regenerate the collection after any copy change (a CI drift check is requested
in `.audit/handoffs/ef-from-g.md`):

```bash
python scripts/gen_native_review.py            # write the sheet
python scripts/gen_native_review.py --check    # fail when it is stale
python scripts/check_glossary.py               # terminology gate
```

## How a review is recorded

Do not edit the generated table. Record every decision here, one row per
concern, so the same question is not re-litigated:

| # | file:line or key | reviewer | date | decision (approve / replace with X / explain) |
|---|---|---|---|---|
| | | | | |

Then apply accepted changes in `apps/web/src/i18n.ts` (both dictionaries stay
key-parity) or in the term table of the glossary, and re-run the two scripts.

## What this collection covers, and what it misses

Covered:

* every value of the Bangla dictionary in `apps/web/src/i18n.ts` (611 strings at
  the time of writing);
* Bangla string literals written directly in `apps/web/src` components;
* Bangla literals in `apps/api/src/bangla_gpt_api` that read like sentences
  (refusals, safety copy, digests, digest/prompt templates). Single-word
  literals are skipped because they are stemmer/expansion lexicons, not copy.

Not covered (stated so it is not mistaken for a clean bill of health):

* text assembled at run time from several fragments, where the fragments are
  individually fine but the sentence is not;
* date and number formatting produced by `Intl` (the policy is Bengali digits on
  Bangla screens, see `apps/web/src/lib/digits.ts`);
* generated questions, worksheets and answer keys — those come from the model
  and from the corpus, and are covered by the RAG evaluation and by teacher
  review, not by this sheet;
* NCTB textbook content itself;
* English copy (the `en` dictionary), which is reviewed separately by whoever
  owns the English release.

## Review order that gets the most value first

1. **Terms** — anything in the table below that contradicts
   `docs/i18n-glossary.md` is a defect, not a preference.
2. **Safety and refusal copy** — `apps/api/src/bangla_gpt_api/services/safety.py`
   and the self-harm/knowledge-boundary responses. Supportive, age-appropriate,
   no invented helpline numbers.
3. **Error and empty states** — `err*` keys, `emptyState*`, `LoadError` copy.
   These are read when a student is already confused.
4. **Assessment copy for teachers** — question paper, worksheet, rubric, answer
   key, marks distribution.
5. **Everything else** — marketing and settings text.

## Open questions the audit is handing over

| Item | Where | Why it needs a person |
|---|---|---|
| lesson plan: `লেসন প্ল্যান` or `পাঠ পরিকল্পনা` | `genLessonPlan`, `lpTitle`, `lpChapterLabel`, `lpGenerate` | both are in use today; the glossary check reports it as `pending` |
| short test: `সংক্ষিপ্ত পরীক্ষা` or `ছোট পরীক্ষা` | `stTitle`, `assignedShortTest`, `notifShorttestAssigned` | same |
| student / teacher / guardian register: `শিক্ষার্থী`/`শিক্ষক`/`অভিভাবক` vs colloquial forms | `roleStudent`, `roleTeacher`, `roleParent` | decides the tone of every screen |
| new copy added by this remediation round | `skipToContent`, `tts*`, `copy*`, `feedback*`, `offline*` keys in `apps/web/src/i18n.ts` | written by an engineer to satisfy an accessibility or state-coverage finding; not reviewed |
| dataset question phrasing | `data/` golden sets | requires a teacher, and is out of scope for this sheet |
