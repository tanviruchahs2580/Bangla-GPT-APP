# Prompt registry

Every prompt this API sends as a system or instruction message lives here as a
versioned file with one owner and a changelog. `manifest.json` is the index;
`services/tutor.py:load_prompt()` is the only reader.

## Layout

```
prompts/
  manifest.json          # id, file, SemVer version, owner, changelog per prompt
  tutor_system.md        # system prompt for the grounded tutor (rules 1-7)
  tutor_grounding_retry.md
  tutor_hint_first.md    # homework-like prompts (A11-03); NEEDS NATIVE REVIEW
  tutor_study_steps.md   # study-mode turns; NEEDS NATIVE REVIEW
  <generator>_system.md  # teacher generators; see "Migration state" below
```

`{{age_rule}}` in `tutor_system.md` is substituted at load time from
`services/safety.AGE_RULE_SENTENCE`, so the child-safety sentence has exactly
one source and cannot drift between the prompt and the safety module.

## Changing a prompt

1. Edit the file.
2. Bump `version` (SemVer: wording/clarification = patch, behaviour change =
   minor, new policy = major) and append a changelog entry with the date and a
   note that says what changed and why.
3. Run the prompt tests and the evaluation gate (see
   `docs/operations/CHANGE_MANAGEMENT.md`); the trace-visible prompt version is
   `id@version+sp-<content digest>`, so a stale version cannot survive.
4. Commit the file, the manifest entry and the test/eval evidence together.

## Migration state (updated 2026-10-19)

Prompts with a `module_constant` field in the manifest still live as constants
in their module and are only *registered* here; `tests/test_rag2_prompt_registry.py`
pins file content == constant content, so the two cannot drift while the
handoff (switch the generator modules to `load_prompt`) is open. Once a module
switches, its manifest entry loses `module_constant` and the file becomes the
only copy.

## Verification

* registry completeness, owners, changelogs and SemVer:
  `pytest tests/test_rag2_prompt_registry.py`
* the loaded versions and the system-prompt digest: same file; the digest of
  the pre-registry text is pinned (`BASELINE_SYSTEM_PROMPT_DIGEST`), so a move
  that changes the prompt text fails the test.
