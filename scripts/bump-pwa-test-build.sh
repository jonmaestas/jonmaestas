#!/usr/bin/env bash
# Bump pwa-test build: HTML __PWA_TEST_BUILD__ + SW CACHE_VER + build.json
set -euo pipefail
cd "$(dirname "$0")/.."

STAMP="$(date -u +%Y%m%d%H%M%S)"
V="v1-${STAMP}"

sed -i.bak -E "s/window\.__PWA_TEST_BUILD__ = \"[^\"]*\"/window.__PWA_TEST_BUILD__ = \"${V}\"/" pwa-test/index.html
rm -f pwa-test/index.html.bak

sed -i.bak -E "s/const CACHE_VER = \"[^\"]*\"/const CACHE_VER = \"${V}\"/" pwa-test/sw.js
rm -f pwa-test/sw.js.bak

printf '{\n  "build": "%s"\n}\n' "$V" > pwa-test/build.json

echo "bumped pwa-test to ${V}"
