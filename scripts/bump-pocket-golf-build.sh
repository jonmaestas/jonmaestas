#!/usr/bin/env bash
# Bump Pocket Golf cache-bust tokens before commit/deploy.
# Usage: from repo root → ./scripts/bump-pocket-golf-build.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
HTML="pocket-golf.html"
JSON="pocket-golf-build.json"
SW="pocket-golf-sw.js"
if [[ ! -f "$HTML" ]]; then
  echo "missing $HTML" >&2
  exit 1
fi
SHORT="$(git rev-parse --short HEAD 2>/dev/null || echo local)"
STAMP="$(date +%Y%m%d%H%M%S)"
BUILD="${SHORT}-${STAMP}"
# Update window.__PG_BUILD__ = "..." in HTML
if grep -q 'window.__PG_BUILD__' "$HTML"; then
  sed -i.bak -E "s/window\.__PG_BUILD__ = \"[^\"]*\"/window.__PG_BUILD__ = \"${BUILD}\"/" "$HTML"
  rm -f "${HTML}.bak"
else
  echo "window.__PG_BUILD__ not found in $HTML" >&2
  exit 1
fi
# Bump CACHE_VER in service worker so browsers see a new SW file and update.
if [[ -f "$SW" ]] && grep -q 'CACHE_VER =' "$SW"; then
  sed -i.bak -E "s/const CACHE_VER = \"[^\"]*\"/const CACHE_VER = \"v1-${STAMP}\"/" "$SW"
  rm -f "${SW}.bak"
fi
printf '{"b":"%s","t":%s}\n' "$BUILD" "$(date +%s)" > "$JSON"
echo "Pocket Golf build → $BUILD"
echo "  updated $HTML  (__PG_BUILD__)"
echo "  updated $SW    (CACHE_VER = v1-${STAMP})"
echo "  updated $JSON"
