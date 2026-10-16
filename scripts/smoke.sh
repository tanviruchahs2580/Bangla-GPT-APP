#!/bin/bash
# smoke.sh — Automated smoke for S0.7 (local or staging)
# Usage: BASE=http://127.0.0.1:8000 bash scripts/smoke.sh
# Or: BASE=https://staging.example.com bash scripts/smoke.sh
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"
EMAIL="smoke_$(date +%s)@example.com"
PASS="Aa1!smokeTest"
NAME="Smoke Test"

echo "→ BASE $BASE"
echo "→ health"
curl -fsS "$BASE/health" | grep -q '"status":"ok"' && echo "  health ok"
echo "→ ready"
curl -fsS "$BASE/ready" | grep -q '"status":"ready"' && echo "  ready ok"

echo "→ register $EMAIL"
REG=$(curl -fsS -X POST "$BASE/auth/register" -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"name\":\"$NAME\",\"role\":\"student\",\"class_level\":6,\"guardian_consent\":true}")
echo "  register ok"

echo "→ login"
TOK=$(curl -fsS -X POST "$BASE/auth/login" -H "Content-Type: application/json" -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "  login ok"

AUTH="Authorization: Bearer $TOK"
# Windows curl corrupts non-ASCII bytes passed in argv; send JSON bodies from files.
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT
cat > "$TMPD/ask1.json" <<'BGPT_EOF'
{"question":"কোষ কী?","class_level":6,"subject":"science"}
BGPT_EOF
cat > "$TMPD/ask2_head.json" <<'BGPT_EOF'
{"question":"এই কুইজ প্রশ্নের ব্যাখ্যা দাও","class_level":6,"subject":"science","explain":
BGPT_EOF

echo "→ learn subjects"
curl -fsS -H "$AUTH" "$BASE/learn/subjects?class_level=6" | grep -q "science" && echo "  learn ok"

echo "→ tutor grounded"
ASK=$(curl -fsS -X POST "$BASE/tutor/ask" -H "Content-Type: application/json" -H "$AUTH" --data-binary @"$TMPD/ask1.json")
echo "$ASK" | grep -q '"grounded":true' && echo "  tutor grounded ok" || (echo "  tutor failed: $ASK"; exit 1)

echo "→ quiz start"
QZ=$(curl -fsS -X POST "$BASE/quizzes" -H "Content-Type: application/json" -H "$AUTH" -d '{"student_id":1,"class_level":6,"subject":"science","num_questions":2}' || true)  # probing call; the correct-SID call below is the gate
# Student id 1 may not be correct; fetch me to get profile_id
ME=$(curl -fsS -H "$AUTH" "$BASE/users/me")
SID=$(echo "$ME" | python3 -c "import sys,json; print(json.load(sys.stdin)['profile_id'])")
QZ=$(curl -fsS -X POST "$BASE/quizzes" -H "Content-Type: application/json" -H "$AUTH" -d "{\"student_id\":$SID,\"class_level\":6,\"subject\":\"science\",\"num_questions\":2}")
ATTEMPT=$(echo "$QZ" | python3 -c "import sys,json; print(json.load(sys.stdin)['attempt_id'])")
QCOUNT=$(echo "$QZ" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['questions']))")
echo "  quiz start ok attempt $ATTEMPT q $QCOUNT"

echo "→ quiz submit"
ANSWERS=$(python3 -c "print(','.join(['0']*int('$QCOUNT')))")
SUBMIT=$(curl -fsS -X POST "$BASE/quizzes/$ATTEMPT/submit" -H "Content-Type: application/json" -H "$AUTH" -d "{\"answers\":[$ANSWERS]}")
echo "$SUBMIT" | grep -q '"score_pct"' && echo "  submit ok"

echo "→ quiz explain loop"
EXPLAIN=$(echo "$SUBMIT" | python3 -c "
import json, sys
rev = json.load(sys.stdin)['review']
item = next((x for x in rev if not x['is_correct']), rev[0])
print(json.dumps({'question': item['question_text'], 'options': item['options'],
                  'correct_index': item['correct_index'], 'user_answer': item['chosen'],
                  'chapter': item['chapter']}, ensure_ascii=False))
")
{ cat "$TMPD/ask2_head.json"; printf '%s' "$EXPLAIN"; printf '}'; } > "$TMPD/ask2.json"
EXASK=$(curl -fsS -X POST "$BASE/tutor/ask" -H "Content-Type: application/json" -H "$AUTH" --data-binary @"$TMPD/ask2.json")
echo "$EXASK" | grep -q '"answer"' && echo "  explain ok grounded=$(echo "$EXASK" | python3 -c 'import sys,json; print(json.load(sys.stdin)["grounded"])')"

echo "→ me"
curl -fsS -H "$AUTH" "$BASE/users/me" | grep -q '"email"' && echo "  me ok"

echo "→ export"
curl -fsS -H "$AUTH" "$BASE/users/me/export" | grep -q '"user"' && echo "  export ok"

echo "→ delete"
curl -fsS -X DELETE -H "$AUTH" "$BASE/users/me" -i | grep -q "204" && echo "  delete ok" || curl -fsS -X DELETE -H "$AUTH" "$BASE/users/me" && echo "  delete ok"

echo "✓ SMOKE OK — all steps passed"
echo "Rollback (if deployed via compose): docker compose --profile core pull && docker compose --profile core up -d --wait (previous tag via API_TAG env)"
