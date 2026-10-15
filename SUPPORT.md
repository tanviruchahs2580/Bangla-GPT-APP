# Support

Bangla GPT APP is maintained by a small group. There is no support SLA.

## Something is broken

Open a public issue — that is the right channel for ordinary bugs:

https://github.com/tanviruchahs2580/Bangla-GPT-APP/issues

Please include the version or commit, what you did, what happened instead,
and the relevant log lines. Redact real student names, emails and phone
numbers: this project holds children's data and an issue is public.

## Something is a security problem

Not a public issue. See [SECURITY.md](SECURITY.md).

## A question

Open a discussion or an issue. If the answer is generally useful, add it
to the documentation in the same pull request rather than leaving it in a
thread where the next person will not find it.

## What support will not cover

- Deployment of the reference stack to a third-party host.
- Data recovery from a lost or corrupt database; take the nightly backups
  (`scripts/pg_backup.sh` for a one-shot, `scripts/backup_loop.py` to
schedule it) seriously.
- Requests to export or look up another person's data. Data access goes
  through [SECURITY.md](SECURITY.md), not support.