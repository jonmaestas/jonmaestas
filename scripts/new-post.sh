#!/usr/bin/env bash
# Creates blog/DATE-SLUG.html from stdin and rebuilds the site.
# Usage: cat post-content.html | bash scripts/new-post.sh "Title" "slug" "2026-05-18" "Description"
#
# post-content.html format (CSS block optional; without BODY markers all of stdin is the body):
#   <!-- BODY -->
#   <p>Paragraph 1</p>
#   <!-- /BODY -->
#   <!-- CSS -->
#   <style>...</style>
#   <!-- /CSS -->
set -euo pipefail
python3 "$(dirname "$0")/build.py" new-post "$@"
echo ""
echo "Next: git add -A && git commit -m \"post: ${1:-Untitled}\" && git push origin main"
