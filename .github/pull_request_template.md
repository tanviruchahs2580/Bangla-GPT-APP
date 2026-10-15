name: Pull request
description: A change to the code, its documentation or its dependencies
labels: ["needs-review"]
body:
  - type: markdown
    attributes:
      value: |
        `CONTRIBUTING.md` is the definition of done. The two rows that catch
        the most people: run `npm run format:check` before pushing, and if
        you touched `db/models.py`, add the alembic migration in this same PR.

  - type: textarea
    id: what
    attributes:
      label: What changed and why
      description: The problem first, then the approach.
    validations:
      required: true

  - type: textarea
    id: verification
    attributes:
      label: How it was verified
      description: >
        Be specific. "757 passed" is verification; "the new test asserts that
        X fails without this change, and it does" is better. Name the commands
        you ran and the numbers you saw.
      render: shell
    validations:
      required: true

  - type: textarea
    id: migration
    attributes:
      label: Alembic migration
      description: >
        If you changed apps/api/src/bangla_gpt_api/db/models.py, paste the
        revision id. Otherwise write "none".
    validations:
      required: true

  - type: textarea
    id: contract
    attributes:
      label: API contract change
      description: >
        Did a request or response shape move? If so, docs/API.md and the
        golden set need updating in this same PR.

  - type: dropdown
    id: area
    attributes:
      label: Area
      options:
        - API routes / services
        - Database / migrations
        - Web frontend
        - CI / deployment / infrastructure
        - Documentation
        - Dependencies
        - Retrieval / AI quality
    validations:
      required: true

  - type: checkboxes
    id: done
    attributes:
      label: Definition of done
      options:
        - label: CI is green on this branch.
          required: true
        - label: New behaviour has a test that fails without the change.
          required: true
        - label: CHANGELOG.md is regenerated (scripts/gen_changelog.py).
          required: true