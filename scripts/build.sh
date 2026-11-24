#!/usr/bin/env bash
# Regenerates the whole site from data/site.json, scripts/templates/ and blog/ posts.
# Run after adding or editing a post, a product, or a template.
set -euo pipefail
exec python3 "$(dirname "$0")/build.py" "$@"
