# Logging: level policy and structure

Status: written by the wave-4 audit (R4-wsC, I-01). This is the documented
level policy the catalog item asks for; it describes what `configure_logging`
(`apps/api/src/bangla_gpt_api/logging_config.py`) installs on every boot.

## Structure

One root handler: a UTF-8-safe stream writer wrapped so a stream that cannot
encode Bangla receives ASCII escapes instead of dying mid-record
(`_EncodingSafeStream`), with key-name based redaction applied twice (logger
level and handler level, `RedactionFilter`/`RedactingFormatter`). Every
application line goes through `json_log` and is one JSON object per line.

## Level policy

| Logger | Level | Why |
| --- | --- | --- |
| root (`""`) | `LOG_LEVEL` env, default `INFO` | the single knob every app logger inherits |
| `bangla_gpt_api.access` | inherits (INFO) | one structured record per request (`op=http_request`): method, route template, status, latency, pseudonymous `user_ref` + `tenant_ref`, client ip, request/trace id, error class |
| `bangla_gpt_api.trace` | inherits (INFO) | one record per pipeline stage (retrieval, generation, grading) when tracing is enabled |
| `uvicorn.access` | WARNING | the app's own access record replaces it; letting uvicorn's line through would double per-request volume with an unredacted, unstructured duplicate |
| `uvicorn.error` | inherits | real startup/shutdown faults must surface |
| `sqlalchemy.engine` | inherits | engine `echo` is never enabled in production settings; if a deployment turns it on deliberately, its lines are subject to the same redaction filter at the root |

Overrides live in exactly one place (`LOGGER_LEVEL_OVERRIDES` in
`logging_config.py`) so the table above cannot drift from the code.

## Redaction and volume guards

- Redaction rules: key-name match (`password`, `token`, `authorization`, ...)
  plus value-shape fallbacks (JWT/argon2/vendor tokens, phone/email shapes)
  applied before serialisation, so field names stay authoritative.
- The access record is rate-of-lines bounded by construction: one line per
  request, no body payloads, ids pseudonymised via HMAC with the deployment
  secret (`u_` accounts, `s_` tenants).

## Sample access line

```json
{"event": "access", "op": "http_request", "method": "POST", "route": "/tutor/ask",
 "status": 200, "latency_ms": 812.4, "user_ref": "u_2b9f4c1d7e0a",
 "tenant_ref": "s_5c81e2f0a9d3", "client_ip": "203.0.113.7",
 "request_id": "9f1c...", "trace_id": "9f1c..."}
```
