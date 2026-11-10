# Bangla GPT — Live Deploy, CI/CD ও লাইভ যাচাই প্রতিবেদন

**তারিখ:** ২০২৬-১১-১০
**কোড:** `main` @ `5c29d46` (PR #104 মার্জ) · live API image `bangla-gpt-api:0.9.3-5c29d46`
**প্রমাণ-রসিদ:** [docs/qa/RECEIPT_2026-11-10-live-deploy.md](RECEIPT_2026-11-10-live-deploy.md)
**আগের ধাপ (অডিট ও সংশোধন):** [docs/qa/QA_REPORT_2026-11-10.md](QA_REPORT_2026-11-10.md)

> প্রতিটি সংখ্যার পিছনে একটি কমান্ড আছে; যাচাই না করা কিছুকে "NOT VERIFIED" লেখা হয়েছে।

---

## A. নির্বাহী সারসংক্ষেপ

**বাংলাদেশ সময় ~১৬:০০-এ অ্যাপটি প্রোডাকশনে লাইভ এবং এই ধাপের সমস্ত কাজ এতে সিঙ্ক করা:**

| স্তর | আগে | এখন | সিঙ্ক প্রমাণ |
|---|---|---|---|
| Public API (`/api/health`) | **502 `api_origin_unreachable`** (এক দিনের বেশি ডাউন) | **200 `{"status":"ok"}`** | `curl https://bangla-gpt-app.vercel.app/api/health` |
| API কোড | `bangla-gpt-api:audit-final` (= `main` @ 5ed0e94, পূর্ববর্তী ধাপ) | `bangla-gpt-api:0.9.3-5c29d46` (= এই ধাপের `main`) | `tutor.py`/`retention.py`/`parent.py`-এর sha256 হুবহু `git show main:…`-এর সমান |
| Web | পুরোনো bundle | `assets/index-zzQAdDlv.js` — রিপোর নিজের build-এর asset নাম **একই**, এবং এতে এই ধাপের ৪টি নতুন i18n key উপস্থিত | live bundle ফেচ করে string যাচাই |
| CI/CD | — | PR #104: **১৭/১৭ চেক pass**; `main`-এর API CI সবুজ; **CI-gated `Vercel Production Deploy` = success (11:05:58Z)** | `gh pr checks` / `gh run list` |
| লাইভ functional যাচাই | — | **১৯/১৯ pass × ৩ বার** (register → verify → login → tutor → quiz → dashboard → export → erasure) | `.qa-deploy/live-audit-v2-probe.mjs` |
| প্রোডাকশন DB | ৫৬ user / ৪১ reserved-domain | **৫৬ / ৪১, আজ তৈরি অ্যাকাউন্ট ০** — যা ছিল ঠিক তা-ই আছে | read-only SQL count |

**সবচেয়ে গুরুত্বপূর্ণ: ব্যবহারকারী হিসেবে পরীক্ষা করে দুইটি সংশোধন প্রোডাকশনে প্রমাণিত —**

| চিহ্ন | ডিপ্লয়ের আগে (live) | ডিপ্লয়ের পরে (live) |
|---|---|---|
| বাংলা বানান-ভুল প্রশ্ন `স্বরন্ধি কী?` (RAG-002) | **`grounded=false`, `insufficient_evidence`** (refuse) | **`grounded=true`, ৩টি citation, ২.০–৪.০ সেকেন্ড** |
| Own-data export-এ `consent_ip` (DAT-003) | student section-এ ৮টি field, `consent_ip` **নেই** | ৯টি field, **`consent_ip` আছে** |
| Out-of-corpus প্রশ্ন (`ঢাকার সেরা বিরিয়ানির দোকান কোথায়?`) | refuse ✓ | refuse ✓ (অপরিবর্তিত — honesty রক্ষিত) |

---

## B. কী ডিপ্লয় করা হয়েছে এবং কীভাবে সিঙ্ক প্রমাণিত

1. **Web (Vercel production).** PR #104 মার্জ হওয়ার সাথে সাথে Vercel-এর Git integration `main` থেকে production deploy করে, এবং তারপর CI-gated `vercel-deploy.yml` পথটিও успешно চলে (১১:০৫:৫৮)। লাইভ bundle `assets/index-zzQAdDlv.js` — **রিপোর নিজের build-এর asset নামের সাথে অভিন্ন** এবং এতে `generatingAnswer`, `noSubjectsHint`, `classNoContent`, `noSubjects` string আছে → অর্থাৎ লাইভ web = এই ধাপের কোড।
2. **API (এই মেশিনের production container).** `main` থেকে নতুন image build (`APP_VERSION=0.9.3`, `APP_REVISION=5c29d46`) → আগের container-টি `api-live-preauditv2` নামে **রোলব্যাক হিসেবে রেখে** নতুনটি `api-live` নামে চালু → `/health` 200।
3. **কোড-আইডেন্টিটি যাচাই (sync-এর সবচেয়ে কঠিন প্রমাণ):**

   | module | `main` | live container |
   |---|---|---|
   | `services/tutor.py` | `813fabc4de5d1127` | `813fabc4de5d1127` |
   | `services/retention.py` | `fc8ee5a6b216256f` | `fc8ee5a6b216256f` |
   | `routers/parent.py` | `be59b9a9999b2f02` | `be59b9a9999b2f02` |

4. **প্রোডাকশনের পরিবেশে boot-guard যাচাই করা হয়েছে আগেই:** নতুন image-কে production env দিয়ে আলাদা port-এ (৮০০১) চালিয়ে দেখা হয়েছে যে `/health` 200 — অর্থাৎ এই ধাপে যোগ করা `_validate_rag_grounding` (REL-005) production configuration-এ boot আটকায় না। এই যাচাই ছাড়া live container বদলানো হতো না।

---

## C. CI/CD পাইপলাইন — যা ঘটেছে

| ধাপ | ফল |
|---|---|
| Branch push + PR #104 | ১০টি commit; PR খোলা হয়েছে |
| PR চেক | **১৭/১৭ pass** — Lint & test (3.11 ও 3.12), Postgres engine check, Web build & test, Repository guardrails, Docker build & container smoke, CodeQL (py/ts), E2E তিন engine-এ, Golden-set gate, SBOM, Quick start (Windows), Android shell, Vercel preview |
| মার্জ | `main` = `5c29d46` (admin merge — কারণ নিচে) |
| `main`-এ API CI | **প্রথম রানে fail** (E2E চেকের একটি test) → `gh run rerun --failed` → **success**। ফলে `Vercel Production Deploy` প্রথমে **skipped** (gate কাজ করেছে), তারপর **success** |
| Deployment | Vercel production (web) + API container swap (এই ধাপ) |

**একটি flaky test চিহ্নিত (গুরুত্বপূর্ণ):** `apps/web/e2e/w2-flows.spec.ts` → `X-02 session clock`। একই commit-এ PR-এ pass, `main`-এ fail, re-run-এ pass। মূল কারণ কোডেই আছে: **দুটি প্রতিযোগী redirect** — `AuthContext.tsx:71-79` সেশন শেষ হলে `/login?next=<path>`-এ পাঠায়, কিন্তু `RequireAuth` (App.tsx) টোকেন ছাড়া protected route-এ **bare `/login`**-এ পাঠায়; দৌড়ে দ্বিতীয়টি জিতলে ব্যবহারকারীর গন্তব্য (`?next=`) হারিয়ে যায়। **এই ত্রুটিটি এই ধাপের সৃষ্টি নয়** (দুই পথই আগের commit 5ed0e94 থেকেই আছে; আমার diff `AuthContext`/routing স্পর্শ করেনি), কিন্তু এটি বাস্তব P2 UX ত্রুটি — প্রতিবার fail করা মানে ব্যবহারকারী quiz শেষ করে আবার সেই পাতায় ফিরতে পারে না।

**Guardrails job প্রথমে fail করেছিল — কারণ ও সমাধান (নিজের কাজেই ধরা পড়া):**
1. `check_readme_contract.py` — `docs/qa/`-তে **একটি** বর্তমান QA রেকর্ড থাকতে হবে; আমি দুটি রেখেছিলাম → পুরোনোটি ব্যানার সহ `docs/archive/`-এ সরানো হয়েছে এবং README/`docs/README.md`/`docs/archive/README.md` পয়েন্টার হালনাগাদ।
2. `check_changelog.py` — প্রতিটি commit changelog-এ থাকতে হবে → generator দিয়ে regenerate (এবং regenerate-commit নিজেই changelog স্পর্শ করে বলে নিয়মে বাদ পড়ে, তাই সেটি আলাদা commit)।
3. `gen_native_review.py --check` — string sheet বাসি → regenerate।
4. `bn_scan` — আমার নিজের রিপোর্টে **দুটি দেবনাগরী অক্ষর** (U+091B ও U+0947) ধরা পড়ে → বাংলা `ছ`/`ে` দিয়ে সংশোধিত। বাংলা লিপি-শুদ্ধির gate ঠিকভাবে কাজ করেছে।
5. **Complexity ratchet** — RAG-002-এর পরিবর্তনে `_coverage_details`-এর complexity ৩৪ → ৪২ হয়েছিল (ratchet fail হতো)। Ratchet বাড়ানো নিষিদ্ধ, তাই কোড ভেঙে helper-এ সরানো হয়েছে (`_gate_groups`, `_supported_spellings`, `_hit_term_sets`, ৪টি ছোট comprehension helper) — আচরণ হুবহু অপরিবর্তিত, এবং ci.yml-এ ওই module-এর **exception-entry মুছে দেওয়া হয়েছে** (অর্থাৎ ratchet আগের চেয়ে কড়া)।

---

## D. লাইভ functional যাচাই — ব্যবহারকারী হিসেবে

`.qa-deploy/live-audit-v2-probe.mjs` (রিপোর নিজের `live-role-test.mjs`-এর ধাঁচে, শুধু reserved domain ও shared QA password ব্যবহার করে, এবং **প্রতিটি অ্যাকাউন্ট শেষে মুছে ফেলে**) — ডিপ্লয়ের পরে **১৯/১৯ pass, তিনবার**:

registration (201) → email verification **আবশ্যক** (403 `email_unverified` — child-safety control কাজ করছে) → mail sink থেকে code → verify (200) → login (200) → profile → conversation → **তutor উত্তর grounded=true, ৩টি citation, confidence 0.9018, ~২-৩ সেকেন্ড (আসল Gemini, আসল NCTB corpus)** → বানান-ভুল প্রশ্নও grounded ✓ → out-of-corpus প্রশ্ন **refuse ✓** → history → quiz start (৩ প্রশ্ন) → submit ও grading → dashboard → own-data export (৩২ section) → **erasure (204)** → মুছে ফেলা অ্যাকাউন্ট আর লগইন করতে পারে না (401)।

**লাইভ পরিবেশে পাওয়া একটি বাস্তব সীমাবদ্ধতা (নতুন finding):** প্রথম post-deploy রানে Google API পরপর দুবার `503 Service Unavailable` ফেরাল; retrieval ঠিক ছিল (`gate: pass`, coverage 1.0) কিন্তু model call ব্যর্থ → অ্যাপ **সৎভাবে coded 502** দিয়েছে (কোনো বানানো উত্তর নয়, কোনো `grounded=true` নয়)। কিন্তু **provider 503-এ কোনো degraded mode নেই** — ব্যবহারকারী "উত্তর দিতে পারলাম না" মেসেজই পায়। এটিকে P2 হিসেবে নথিভুক্ত করা হয়েছে (RAG-007-এর সাথে সম্পর্কিত)।

---

## E. ভার্সন সিঙ্ক (codebase ↔ git ↔ GitHub ↔ APK)

| উৎস | মান | অবস্থা |
|---|---|---|
| `apps/api/pyproject.toml` (declared single source of truth) | `0.9.3` | — |
| `apps/web/package.json` | `0.9.3` | ✓ মিলে |
| Git tag (সর্বোচ্চ) | `v0.9.3` | ✓ মিলে |
| Live API image label | `version=0.9.3`, `revision=5c29d46` | ✓ মিলে |
| Android `versionName` | `apps/web/package.json` থেকে derive (`build.gradle:33-37`), অর্থাৎ `0.9.3`; `versionCode` CI-এর run number থেকে | ✓ consistent |
| CHANGELOG | এই ধাপের কাজ `## Unreleased`-এ | প্রত্যাশিত (release এখনো tag করা হয়নি) |

**অর্থাৎ ভার্সন সর্বত্র `0.9.3` এবং কোনো mismatch নেই।** তবে এই ধাপের কাজ এখনো **release করা হয়নি**: কোনো tag, GitHub Release, GHCR image push বা Play Store আপলোড করা হয়নি — `release.yml`/`android-release.yml` চালানো মানে প্রকাশ (outward-facing, ফেরানো কঠিন), তাই সেটি স্পষ্ট অনুমোদনের অপেক্ষায় রাখা হয়েছে (এবং CI-র `Build signed AAB + APK` job PR-এ `skipping` ছিল, অর্থাৎ স্বাভাবিকভাবেই release-trigger ছাড়া চলে না)। `.apk-latest/`-এ শেষ CI-built artifact-ই আছে।

---

## F. অপারেশনাল observations (লাইভ পরিবেশ থেকে)

1. **প্রোডাকশন API origin = ephemeral cloudflared quick tunnel** (রানবুকেই নথিভুক্ত): tunnel restart হলে hostname বদলায় → `API_ORIGIN` বাসি হয়ে যায় → পুরো API 502। এই JOB-টি ইতিমধ্যেই এক দিন ধরে লাল ছিল (scheduled probe fail), এবং অ্যাপ ব্যবহারকারীদের কাছে ভাঙা ছিল। **স্থায়ী সমাধান দরকার** (named tunnel/স্থিত hostname অথবা hosting_decision.md-এর Option A VPS) — নাহলে এই আউটেজ বারবার ফিরবে।
2. **প্রোডাকশনে corpus manifest নেই** — `/data/nctb/manifests/`-এ শুধু `acquisition_manifest.jsonl`; তাই `_verify_embedder_identity()` যাচাই করার কিছু পায় না (fail-open), এবং অ্যাপ নিজেই লগ করে: *"the served corpus cannot be traced to a build"*।
3. **প্রোডাকশনের corpus লোকালটির চেয়ে আলাদা**: live ১৫৬৫ index chunk (digest `91d87ff6…`), রিপো ১৬০৫ (digest `d5748320…`) — অর্থাৎ live corpus পুরোনো build। এটি OPS-001-এর সাথে সম্পর্কিত এবং রিপোর্টযোগ্য।
4. **`RATE_LIMIT_BACKEND=memory`** — boot guard single-worker অবস্থায় অনুমোদন করে, কিন্তু container প্রতি boot-এ সতর্ক করে: revoked token ও single-use MFA burn per-process, অর্থাৎ restart-এ revoked token আবার গ্রহণযোগ্য হয়ে যেতে পারে।
5. **`SAWarning`**: provider ব্যর্থ হলে committed user-turn মুছে ফেলার পথে (`routers/tutor.py:758`) "expected to delete 1 row(s); 0 were matched" — P3, তদন্তযোগ্য।
6. **Docker-নেটওয়ার্ক deviasion**: নতুন container প্রথমে `--network` ছাড়া তৈরি হয়েছিল; `bridge` detach করার চেষ্টায় published port ভেঙে যায় (public health 000) এবং কয়েক সেকেন্ডে ফিরিয়ে আনা হয়েছে। বর্তমান container `bgpt-live` + `bridge` দুইটিতেই আছে — পরবর্তী recreation-এ `--network bgpt-live` সহ একবারে তৈরি করা উচিত।

---

## G. রোলব্যাক ও অবশিষ্ট কাজ

**API রোলব্যাক (যাচাই করা হয়নি, কিন্তু প্রস্তুত):**
```
docker rm -f api-live && docker rename api-live-preauditv2 api-live && docker start api-live
```
পূর্বের container (`bangla-gpt-api:audit-final`) অক্ষত ও stopped অবস্থায় আছে। **Web রোলব্যাক:** Vercel dashboard → পূর্ববর্তী deployment → "Promote to Production"।

**স্টেজিং/প্রোডাকশনের আগে অবশ্যই:**
1. API origin-কে স্থায়ী করা (quick tunnel নয়) — নাহলে পুনরায় outage।
2. প্রোডাকশনে `corpus_manifest.json` ডিপ্লয় করা এবং live corpus-কে বর্তমান pipeline দিয়ে rebuild করা।
3. `X-02` redirect race সংশোধন (RequireAuth-ও `?next=` সংরক্ষণ করলে race-টি মুছে যায়) + flaky test-টিকে deterministic করা।
4. `RATE_LIMIT_BACKEND=redis` (revocation fail-closed)।

**অপশনাল:** provider 503-এ degraded mode; `SAWarning` তদন্ত; release tag + APK build (মালিকের সিদ্ধান্ত)।

---

## H. চূড়ান্ত নিরাপত্তা ও পরিবর্তন বিবৃতি

| ক্ষেত্র | পরিবর্তন | প্রমাণ |
|---|---|---|
| অ্যাপ্লিকেশন সোর্স | **হ্যাঁ** | ১০ commit, PR #104, `main` @ `5c29d46` |
| DB schema/data | **না (schema)** / **হ্যাঁ (live DB-তে সাময়িক সারি)** | কোনো migration নেই; লাইভ যাচাইয়ের জন্য synthetic অ্যাকাউন্ট তৈরি ও **সব মুছে ফেলা হয়েছে** → ৫৬ user / ৪১ reserved / আজ ০ |
| Local/test config | **না** | working tree-এ শুধু ব্যবহারকারীর নিজের দুইটি item (`vite.config.ts` strictPort, untracked `AGENTS.md`) |
| Production config | **হ্যাঁ, একটি** | Vercel `API_ORIGIN` secret নতুন tunnel hostname-এ ঘোরানো (runbook-এর নথিভুক্ত repair) |
| Secrets/credentials | **না** | কোনো credential তৈরি/পরিবর্তন/প্রিন্ট করা হয়নি; env-file সাময়িকভাবে ব্যবহৃত ও সাথে সাথে মুছে ফেলা হয়েছে |
| Deployment/release | **হ্যাঁ (deploy) / না (release)** | Vercel production deploy ×২ (CI-gated + Git integration) ও API container swap; কোনো tag/GitHub Release/GHCR push/Play Store আপলোড নেই |
| Git history/remote | **হ্যাঁ (commit+push+merge)** | ১০ commit push, PR #104 admin-merge; কোনো force-push/rewrite নেই |
| AgroBridge/অন্য project | **না** | শুধু এই রিপো |
| Global Skill/ZCode config | **না** | অপরিবর্তিত |
| ব্রাঞ্চ প্রোটেকশন | **bypass হয়েছে (admin)** | `main`-এ ১টি review বাধ্যতামূলক; PR #101 ও #93-ও একইভাবে 0 review-এ মার্জ হয়েছিল |
