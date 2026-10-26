# Native-speaker review record — Bangla copy

The companion to [`native-review/ui-strings.md`](native-review/ui-strings.md),
which lists every user-facing Bangla string with its `file:line` and key. That
file is generated; this one is the **record**, and it is hand-written.

## Status

| Area | Strings | Reviewed | Notes |
|---|---|---|---|
| In-app copy (`apps/web/src/i18n.ts`) | see the sheet | ☐ not started | needs a native speaker |
| Literals outside the dictionary | see the sheet | ☐ not started | the sheet marks them `(literal)` |
| API user-facing copy (refusals, safety, digests) | see the sheet | ☐ not started | |
| Play Store listing copy (ships with the Play pack) | 2 descriptions + 15 bullets | ☐ not started | submission-blocking |

Nothing above has been reviewed. This file exists so the review has a place to
land — a review that lives in a chat thread is not a review.

## How to review

1. Open `docs/native-review/ui-strings.md` and read the `text` column.
2. Flag anything unnatural, machine-translated, wrongly formal or informal for a
   class 6–10 student, inconsistent with the same term elsewhere, or whose
   Bengali changes the meaning of the English original.
3. Write the decision here as a row (see the table below), and update the
   dictionary/branch in the same change that lands the correction.
4. After editing copy, re-run `python scripts/gen_native_review.py` — the sheet
   is CI-checked for staleness, so it cannot drift behind the code.

## Decisions

| # | key / file:line | current text | issue | approved text | reviewer | date |
|---|---|---|---|---|---|---|
| | | | | | | |

## Terms that must stay consistent

Bengali terminology in a curriculum product is not a style choice: the same
concept must use the same word everywhere a student can see it. When a term is
decided, add it here so the next string does not silently introduce a synonym.

| Concept | Bengali term | Where it appears | Decided by | date |
|---|---|---|---|---|
| | | | | |
