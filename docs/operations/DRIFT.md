# Drift monitoring: query topics, corpus coverage, curriculum staleness

Owner: ai-platform. Finding: AUD-A2-13 (A10-04). Script:
`apps/api/scripts/drift_report.py` (offline, no network, no key).

## What drift means here

Two drifts hurt a curriculum-grounded tutor, and both are visible without
reading a single student message:

1. **Topic drift** — what students ask about versus what the corpus covers.
   - demand with no coverage = a curriculum-gap backlog item (the corpus needs
     a chapter, or the refusal is the honest answer until it arrives);
   - coverage with no demand = a thinning candidate.
2. **Corpus staleness** — the corpus was built from a specific textbook
   edition (`curriculum_year`, `edition` in
   `data/nctb/manifests/acquisition_manifest.jsonl`). When the manifest records
   a newer edition than the chunks carry, answers are grounded in a superseded
   book.

## Running it

From `apps/api`:

```bash
python scripts/drift_report.py                       # markdown to stdout
python scripts/drift_report.py --json-report report.json --markdown report.md
python scripts/drift_report.py --previous report.json   # adds a diff section
python scripts/drift_report.py --queries aggregate.jsonl  # real (aggregated) traffic
```

Options:

- `--corpus-dir` — defaults to `<repo>/data/nctb`; if it is missing or empty
  the bundled sample corpus is used and the report says so in a `note`.
- `--eval` — the frozen evaluation dataset used as the **query-topic proxy**
  (646 labelled items with class/subject/chapter). It is a proxy, labelled as
  one: it is not real traffic.
- `--queries <jsonl>` — optional aggregate topic counts exported by the
  operator. The only accepted shape is aggregated and text-free:

  ```json
  {"class_level": 6, "subject": "science", "chapter": "কোষ", "count": 12}
  ```

  No student question text is ever read by this script; the privacy posture of
  the platform (no query text in logs or analytics) is what makes an aggregate
  export the only available source.
- `--out` / `--markdown` — write the JSON report and markdown summary.

The report contains: the class×subject grid (chunks, chapters, curriculum
years), the gaps against the product claim (classes 6–10 ×
science/mathematics/bangla), the topic distribution with
`uncovered_demand` / `covered_but_never_asked`, the staleness block
(`corpus_older_than_manifest`, non-acquired sources) and, with `--previous`,
which coverage cells appeared or disappeared and whether the corpus
fingerprint moved.

## Cadence and reaction

| Cadence | Action |
|---|---|
| Weekly (operator) | run the script with the previous report; file new `uncovered_demand` rows in the curriculum-gap backlog |
| On corpus rebuild | run with `--previous`; the fingerprint change must be expected (a rebuild that changes the fingerprint without a corpus commit is an incident) |
| On curriculum update (new NCTB edition) | `corpus_older_than_manifest: true` is the signal to re-acquire and rebuild; the answer quality is not trustworthy for the affected subjects until then |

## Measured run (2026-10-20, real corpus)

Command (writes nothing tracked by default):

```bash
cd apps/api
python scripts/drift_report.py --out ../.audit/tmp/r3/drift_report.json     --markdown ../.audit/tmp/r3/drift_report.md
```

Result on the served corpus (1 565 chunks, fingerprint `f6afeff2da39f36e`;
the 2026-10-19 record was 1 390 chunks / `265566d6893b8d92`):

- **Coverage grid**: every claimed class×subject cell (6–10 × bangla,
  mathematics, science; ICT as a bonus) carries chunks — the gaps section
  reads "none". Class 11/12 physics/chemistry/biology/higher-mathematics
  are present from the HSC curriculum documents.
- **Curriculum staleness**: `corpus_older_than_manifest: false`. The corpus
  carries curriculum years 2012 (secondary) and 2026 (HSC compilation
  headings) and the manifest's newest year is 2012 — the mixed-year corpus
  is visible in the grid's `curriculum years` column, which is the point:
  an edition update shows up there before it shows up in an answer.
- **Query topics** (evaluation-set proxy, 646 items): the distribution is
  recorded per class×subject with `covered_but_never_asked` thinning
  candidates listed (10:bangla among them) and no `uncovered_demand` rows —
  every topic the proxy asks about has corpus coverage.
- The report is a proxy: it reads the frozen evaluation set, not production
  traffic, until the operator exports aggregate counts (`--queries`).

## What this does not do (honest limits)

- It does not read production queries: the topic distribution is a proxy until
  the operator exports aggregates.
- It does not alert: the script exits non-zero only on invalid input. Wiring it
  into a scheduled workflow with a threshold is the follow-up
  (`.audit/handoffs/workflows-rag2.md`).
- It does not measure answer quality drift; that is the evaluation gate's job
  (`docs/operations/CHANGE_MANAGEMENT.md` step 3).
