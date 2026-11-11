# Content and Terminology — Bangla GPT frontend renovation

The product is Bengali-first with a full English dictionary. This file records the strings
this renovation added or changed, the rules that govern Bengali text in this codebase, and
the terminology still unresolved.

**Method:** the Bangla dictionary (`bn`) is the source of truth for the key set —
`type Dict = Record<keyof typeof bn, string>` (`src/i18n.ts:841`) makes a missing English key
a **compile error**, not a runtime fallback. That is why both dictionaries were extended
together and why `tsc` is part of the gate set.

---

## 1. Strings added or changed by this renovation

| Key | Bangla | English | Why |
|---|---|---|---|
| `offlineDeleteFailed` | ডাউনলোড করা অধ্যায়টি মুছা যায়নি — আবার চেষ্টা করুন। | Could not delete the downloaded chapter — please try again. | **R-06.** The delete failure was silent; the student had no way to know the copy was still there. The copy is verb-led, names the object, states the outcome, and gives the next action. |
| `qpAcceptOne` | এটি অনুমোদন করুন | Accept this one | **R-11.** The per-question button reused `qpReviewAll` ("সব অনুমোদন করুন" / "Accept all"), so a single-row action read as a bulk one. |

Both new strings follow the house style established by the surrounding keys: Bengali uses the
Bengali full stop `।`, the em dash `—` for a clause break, and no Latin punctuation.

## 2. Rules this renovation did not break (and did not need to change)

| Rule | Enforced by |
|---|---|
| All user-facing strings go through `t()` — no literal UI copy in JSX | `eslint` + the dictionary shape; both new keys are dictionary entries, not inline strings |
| Numerals follow the active language's policy (`formatNumber`) | `w2_i18n_numeral_policy.test.ts` (9 tests) |
| Bengali body line-height ≥ 1.6, heading ≥ 1.5 | `w2_i18n_css_typography.test.ts:92-101` |
| No `letter-spacing` on Bengali text | five `letter-spacing` sites exist; all are `:lang(en)`-scoped or explicitly allowlisted |
| No `text-transform` on Bengali | two sites, both `:lang(en)` |
| No `hyphens: auto` | asserted |
| Font weights limited to the loaded 400 / 700 faces | asserted against `main.tsx`'s two imports |
| Education terms keep their established meaning — no silent re-translation | this renovation re-translated nothing; the two new keys are new concepts, not replacements |
| Preserve existing localization keys and fallback rules | no key was removed or renamed |
| Official curriculum wording must not be altered without a verified source | no curriculum, textbook, helpline, or citation string was touched. The ১৬২৬৩ / ৯৯৯ helpline numbers are undamaged (asserted by `test_qa_helpline_policy.py` server-side) |

## 3. Mixed-script and Bidirectional handling

Unchanged, and worth recording because a redesign can easily break it:

- Subject values arrive from the API as Latin enums (`"science"`, `"math"`) and are rendered
  through `tSubject()`, so a Bangla sentence never contains a raw machine value. This is
  already the pattern in `OfflineLibrary` (with a comment explaining it) and the renovation
  followed it rather than adding a second path.
- Machine values that must stay Latin — invite codes, model identifiers, API error codes —
  are rendered as-is and kept visually distinct; `.invite-code` is explicitly allowlisted as
  Latin-only for `letter-spacing` purposes.
- The new toast string contains no interpolation, so it introduces no mixed-script risk.

## 4. Confirmed copy/semantics defects fixed

| # | Was | Now | Class of defect |
|---|---|---|---|
| R-11 | Per-question button labelled "Accept all" | `qpAcceptOne` | Mislabel — a bulk word on a single-row action |
| R-12 | Resend-verification rendered as a link to `/forgot` | A `Button`, so it announces as an action | False affordance — the announced role did not match the behaviour |
| R-03 | A failed invite fetch announced an empty list | `LoadError` with a retry | Untruthful empty state |
| R-06 | A failed delete said nothing | Localized failure toast | Missing feedback |

## 5. Unresolved terminology and copy — for the owner, not silently changed

| # | Item | Why it is unresolved |
|---|---|---|
| 1 | `MePage.tsx:504` renders the server string `on_disable_note_code` through `t()` with a raw-value fallback, so an unmapped code can surface as machine text to a child. | The code set is owned by the API and its per-code meaning is not documented in this repository. Inventing Bangla copy for codes whose meaning is unknown would be worse than the fallback. Tracked as **R-17**. |
| 2 | The four unconfirmed destructive actions speak "মুছুন"/"Delete" and act immediately; adding confirmation would require new confirm copy for each. | Confirmation steps are part of the locked contract (**R-13**). If the owner approves adding them, that change needs four new confirmation strings and four dialog tests. |
| 3 | `pages/SchoolDashboard.tsx:9` documents the route as "school_admin / admin". | The doc comment and the gate disagree (**R-14**). The comment is the thing most likely to mislead a future contributor; it should be corrected in the same change that settles the role matrix. |
| 4 | Dashboard page titles (`h1.page-title`) versus student page titles (`h1`) use different margins — 16 px versus `0.4em` — now that the `.page-title` rule actually applies (R-08). | This is a **newly visible** inconsistency rather than an introduced one: the staff rule had been dead, so both were falling back to the base heading margin. Whether staff titles should sit 16 px below versus 0.4em is a small deliberate decision; recorded rather than assumed. |

## 6. Not done

- No new locale was added and no translation framework change was made. There is exactly one
  localization mechanism and it stayed that way.
- No Bengali text was re-translated for style. This renovation adds two keys and changes none
  of the existing ~1,100.
- **No Bangla rendering was inspected on a real device.** Font shaping was verified only
  indirectly — via the CSS guards (line-height floors, no tracking, `font-synthesis: none`),
  the existing Bengali-quality tests, and the visual baselines which include Bangla glyphs at
  three viewports. That is not the same as a native-device glyph review, and it is not claimed
  as one.
