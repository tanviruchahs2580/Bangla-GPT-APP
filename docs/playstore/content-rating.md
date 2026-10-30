# Play Console — Content rating (IARC questionnaire) answers

The rating is assigned by IARC from the questionnaire; the console shows the
result. Answer from this table so the questionnaire matches what the app
actually does.

## Category to pick

**Utility, productivity, communication or other** (not "Game"). An education
app with a chat surface fits IARC's utility category; picking a game category
adds content questions that do not apply.

## Answers

| Question (IARC wording varies slightly) | Answer | Why |
|---|---|---|
| Does the app contain violence? | No | Curriculum content only; the tutor's safety layer refuses violent requests (`services/safety.py`). |
| Sexual content or nudity? | No | Same refusal layer; the safety layer carries a Bangla sexual-content refusal category (`services/safety.py`) while the committed red-team set (`apps/api/eval/redteam_v2.json`) covers override/leak prompts in Bangla and English plus drug, weapon and self-harm prompts. |
| Profanity or crude humour? | No | No user-visible copy uses it. The safety layer has no profanity category (`services/safety.py` refuses self-harm, weapon/drug synthesis, sexual content, violence and personal-data requests); the answer rests on the copy and the school context, not on a filter. |
| References to drugs, alcohol or tobacco? | No | Curriculum science may *mention* substances in a biology context; that is not promotion and IARC's question is about glamourisation/promotion. Answer No; if the console offers a free-text note, say the app is an NCTB curriculum tutor (F-126: the corpus is curriculum documents, not student textbooks). |
| Gambling, simulated gambling, or real-money purchases? | No | No payment path exists in the app at all. |
| Horror, fear or threatening content? | No | |
| **Does the app allow users to interact or exchange content?** | **Yes** | Classes, teacher-authored content and the tutor chat all carry user-generated text. |
| **Can users share personal information?** | **Yes** | A student can type anything into the question box, including personal details. The server redacts phone/email/NID spans before the model call (`services/tutor.py`) and a report-a-problem path exists for chat answers, but the questionnaire asks about capability, not mitigation. |
| Does the app share the user's current location with other users? | No | No location is collected (see `data-safety.md`). |
| Does the app allow users to purchase digital goods? | No | |
| Does the app contain ads? | No | No ad SDK is present. |
| Does the app include user-generated content that is publicly visible? | No | Chat and classroom content is visible only to the participants and their school staff; nothing is published to a public feed. |

## What the answers imply for the listing

- **Target audience & content**: do **not** declare "Designed for Families".
  The target-audience answer is an owner decision (13+ is the proposal) — the
  app itself has **no age gate and collects no date of birth** — and the register flow is guardian-consented,
  but the app is not built to the Families policy's content and ads
  requirements. Declaring it would be a false claim, and Play enforces that
  policy with removals.
- Expect a low rating (PEGI 3 / ESRB Everyone / USK 0-class) because every
  content question is answered No. The console assigns it; do not print a rating
  in the listing before it is assigned.
- The "users can interact" answer enables Play's **user-generated content**
  policy requirements: the app must have a content moderation path and a
  reporting mechanism. Both exist — the safety layer refuses unsafe prompts
  server-side, and `POST /feedback` (a positive/negative rating and/or a comment, attached to a message
  or an attempt) feeds the
  admin AI-quality queue with triage SLAs in `docs/runbook.md`. Point the Play
  review notes at that flow if the reviewer asks.

## Evidence to cite if Play asks

| Requirement | Where it lives |
|---|---|
| Moderation of user content | `apps/api/src/bangla_gpt_api/services/safety.py` (deterministic child-safety layer, refusal copy, academic-context override) |
| Reporting mechanism in-app | `POST /feedback` (rating + optional comment, attached to a message or attempt); the queue admins work is `GET /admin/feedback`, and `GET /admin/ai/quality` is the quality dashboard; triage SLAs in `docs/runbook.md` |
| Data collected / shared | `docs/playstore/data-safety.md` (the answer sheet), backed by the owner-side data-inventory record |
| Child-data handling | Privacy page child-data section (`/privacy`, bn + en) and the guardian-consent requirement at registration |
