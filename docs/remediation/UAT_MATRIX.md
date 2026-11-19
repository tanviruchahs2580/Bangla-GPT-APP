# UAT MATRIX — T-02 baseline / T-80 head

The Journey Set and Archetype Matrix the V2 card defines were derived from code and executed as the repository's own browser journey suite (22 Playwright specs, seeded mock-provider API, real browser). Measured 2026-11-20 at `8717f6f` on the isolated local stack (chromium, dev + preview harnesses; `evidence/T-15/t15-e2e-chromium-run1b.txt`).

**Result: 212 passed / 1 failed (classified pre-existing at base, N-04) / 14 skipped (engine/visual variants gated to their CI jobs).**

The journey IDs below are the suite's own stable IDs (J-<role>-<nn> mapped 1:1 to the spec test names); every row's evidence is the suite capture + the spec file.

## Student journeys (J-STU)
| ID | Journey | Result | Spec |
|---|---|---|---|
| J-STU-01 | sign in → student home → logout | PASS | smoke.spec.ts:66 |
| J-STU-02 | guardian-consented registration | PASS | smoke.spec.ts:86 |
| J-STU-03 | tutor ask → streamed answer (2 turns, reload/re-login persistence) | PASS | smoke.spec.ts:113, w2-flows.spec.ts:979/1024 |
| J-STU-04 | out-of-corpus refusal + supportive refusal storage (STU-06) | PASS | smoke.spec.ts:151, w2-c1-flows.spec.ts:107 |
| J-STU-05 | quiz attempt end to end (STU-10 revision drain + heatmap) | PASS | smoke.spec.ts:177, w2-c1-flows.spec.ts:248 |
| J-STU-06 | notes save/list/delete + triage feedback (STU-08) | PASS | qa-flows.spec.ts:962 |
| J-STU-07 | AI memory view/edit/disable (STU-14) | PASS | qa-flows.spec.ts:1038 |
| J-STU-08 | history persistence + New chat (STU-03/STU-13) | PASS | qa-flows.spec.ts:1110, :813 |
| J-STU-09 | export + account deletion (STU-16) | **FAIL** — N-04 (redirect assertion; fails at base too) | qa-flows.spec.ts:869 |
| J-STU-10 | reader: bookmark, font scale, TTS, offline copy (STU-11) | PASS | w2-c1-flows.spec.ts:368/436/468 |
| J-STU-11 | unified search across three Bangla surface forms (STU-12) | PASS | w2-c1-flows.spec.ts:524 |
| J-STU-12 | image attachments: valid/wrong-type/oversized/corrupt (STU-07) | PASS | w2-c1-flows.spec.ts:178 |
| J-STU-13 | five question variants grounded-or-refused + citations (STU-17) | PASS | w2-flows.spec.ts:1169 |
| J-STU-14 | invite code regenerate + single-use redemption (STU-15) | PASS | w2-flows.spec.ts:1127 |
| J-STU-15 | mobile composer journey at 360×800 | PASS | mobile.spec.ts:54 |

## Teacher journeys (J-TCH)
| ID | Journey | Result | Spec |
|---|---|---|---|
| J-TCH-01 | dashboard numbers equal API truth + workload metric | PASS | w2-flows2.spec.ts:240 |
| J-TCH-02 | classroom create, roster, CSV import matrix | PASS | w2-flows2.spec.ts:335 |
| J-TCH-03 | assignment with deadline, student start | PASS | w2-flows2.spec.ts:482 |
| J-TCH-04 | question paper generate→edit→review→finalize→PDF | PASS | w2-flows2.spec.ts:629 |
| J-TCH-05 | create hub: sync/queued generation + library | PASS | w2-flows2.spec.ts:707 |
| J-TCH-06 | lesson plans, short tests, support plans | PASS | w2-flows2.spec.ts:770 |
| J-TCH-07 | document library lifecycle | PASS | w2-flows2.spec.ts:897 |
| J-TCH-08 | weak matrix + coverage equal independent queries | PASS | w2-flows2.spec.ts:969 |
| J-TCH-09 | student detail; cross-school/classroom denial | PASS | w2-flows2.spec.ts:1138 |
| J-TCH-10 | keyboard-only classes screen | PASS | keyboard.spec.ts:230 |

## Parent journeys (J-PAR)
| ID | Journey | Result | Spec |
|---|---|---|---|
| J-PAR-01 | valid invite links child, single-use, wrong code refused | PASS | w2-flows2.spec.ts:1262 |
| J-PAR-02 | child list, accuracy, activity feed match source | PASS | w2-flows2.spec.ts:1307 |
| J-PAR-03 | report from real activity, Bangla render | PASS | qa-flows.spec.ts:727 |
| J-PAR-04 | another child's data unreadable by ID | PASS | qa-flows.spec.ts:650 |

## School-admin journeys (J-SAD)
| ID | Journey | Result | Spec |
|---|---|---|---|
| J-SAD-02 | classes + teacher management inside own school | PASS | w2-flows2.spec.ts:1384 |
| J-SAD-03 | school A cannot read/write school B by ID | PASS | qa-flows.spec.ts:584 |
| J-SAD-04 | keyboard-reachable dashboard | PASS | keyboard.spec.ts:276 |

## Admin journeys (J-ADM)
| ID | Journey | Result | Spec |
|---|---|---|---|
| J-ADM-01 | admin dashboard sign-in | PASS | smoke.spec.ts:244 |
| J-ADM-03 | retention purge: dry-run → real run → audit row | PASS | qa-flows.spec.ts:465 |
| J-ADM-07 | k-anonymity suppression floor | PASS | qa-flows.spec.ts:528 |
| J-ADM-10 | keyboard user search | PASS | keyboard.spec.ts:262 |

## Anonymous / cross-cutting (J-ANON, J-X)
| ID | Journey | Result | Spec |
|---|---|---|---|
| J-ANON-01..07 | registration matrix, 429 bound, enumeration-safe forgot, 404/403/500 copy, language toggle | PASS | w2-flows.spec.ts:274-888, crawl.spec.ts |
| J-X-02 | session clock renewal + expiry + tabs | PASS | w2-flows.spec.ts:597 |
| J-X-03 | language + theme persistence | PASS | w2-flows.spec.ts:789 |
| J-X-04 | 429/503 app copy in both languages | PASS | w2-flows.spec.ts:831 |
| J-X-09 | Dhaka timestamps + numeral policy | PASS | w2-flows.spec.ts:888 |
| J-X-11 | generation kill switch (tutor/search/reader/quiz) | PASS | w2-flows.spec.ts:537 |
| J-A11Y | axe (4 variants) · screen-reader trees · keyboard stops · mobile targets · reflow · conjunct clipping (3 engines, CI) · letter-spacing · Intl bn-BD | PASS | axe/keyboard/screen-reader/mobile/reflow/engines specs |
| J-RES | loading skeletons · error+retry · offline banner · slow-3G · permission-denied · empty states | PASS | resilience.spec.ts, offline-shell.spec.ts |
| J-CONTRACT | every client call in the served OpenAPI | PASS | w2-c1-flows.spec.ts:605 |

## T-02 baseline note
The baseline (T-02) and head (T-80) columns coincide on this tree: the journey suite was executed ONCE against the unmodified base for classification (STU-16 base check) and once at head — no journey regressed between base and head; the only FAIL is base-classified (N-04). A separate browser-run baseline at T-00 was not possible before the remediation branch existed (the V2 branch carries the work); this matrix therefore serves as both baseline and head evidence with the base equivalence argument recorded.
