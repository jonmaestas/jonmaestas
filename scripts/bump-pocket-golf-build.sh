#!/usr/bin/env bash
# Bump Pocket Golf cache-bust tokens before commit/deploy.
# Usage: from repo root → ./scripts/bump-pocket-golf-build.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
HTML="pocket-golf.html"
JSON="pocket-golf-build.json"
if [[ ! -f "$HTML" ]]; then
  echo "missing $HTML" >&2
  exit 1
fi
SHORT="$(git rev-parse --short HEAD 2>/dev/null || echo local)"
BUILD="${SHORT}-$(date +%Y%m%d%H%M%S)"
# Update window.__PG_BUILD__ = "..."
if grep -q 'window.__PG_BUILD__' "$HTML"; then
  sed -i.bak -E "s/window\.__PG_BUILD__ = \"[^\"]*\"/window.__PG_BUILD__ = \"${BUILD}\"/" "$HTML"
  rm -f "${HTML}.bak"
else
  echo "window.__PG_BUILD__ not found in $HTML" >&2
  exit 1
fi
printf '{"b":"%s","t":%s}\n' "$BUILD" "$(date +%s)" > "$JSON"
echo "Pocket Golf build → $BUILD"
echo "  updated $HTML"
echo "  updated $JSON"
