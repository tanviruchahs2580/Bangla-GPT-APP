#!/usr/bin/env bash
# Rollback game-day drill (M-11).
#
# The release workflow's rollback path was syntax-checked but never
# executed; a rollback that fails in production is the worst possible time
# to learn the drill. This script reproduces the exact rollback sequence
# release.yml runs (checkout previous tag -> pull -> compose up --wait)
# against a STAGING compose project, then asserts the stack is healthy on
# the previous tag.
#
# Usage (from the repo root, on the staging host):
#   ./scripts/rollback_drill.sh [CURRENT_TAG]
#
# Defaults to the newest tag. Requires: docker compose, git tags, a
# configured staging stack (ENV=test, --profile core).

set -euo pipefail

COMPOSE="docker compose --profile core"
CURRENT_TAG="${1:-$(git describe --tags --abbrev=0)}"

echo "== rollback drill: currently deployed tag should be ${CURRENT_TAG}"

echo "== 1. verify the current tag is healthy (precondition)"
git checkout -q "$CURRENT_TAG"
export API_TAG="$CURRENT_TAG" WEB_TAG="$CURRENT_TAG"
$COMPOSE up -d --wait --wait-timeout 120
$COMPOSE ps

echo "== 2. run the release.yml rollback sequence verbatim"
PREV=$(git describe --tags --abbrev=0 "$CURRENT_TAG"^ 2>/dev/null || true)
if [ -z "$PREV" ]; then
  echo "FAIL: no previous tag before $CURRENT_TAG — drill needs >= 2 tags"
  exit 1
fi
echo "rolling back to $PREV"
git checkout -q "$PREV"
export API_TAG="$PREV" WEB_TAG="$PREV"
$COMPOSE pull || true
$COMPOSE up -d --wait --wait-timeout 120

echo "== 3. assert health on the previous tag"
for _ in $(seq 1 30); do
  status=$($COMPOSE ps -q api | xargs -r docker inspect --format '{{.State.Health.Status}}' 2>/dev/null || true)
  if [ "$status" = "healthy" ]; then
    echo "PASS: stack healthy on $PREV (drill complete)"
    echo "note: staging is now intentionally one tag behind; redeploy $CURRENT_TAG when done"
    exit 0
  fi
  sleep 2
done
echo "FAIL: api container did not report healthy on $PREV within 60s"
exit 1
