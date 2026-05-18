#!/usr/bin/env bash
set -euo pipefail

# new-post.sh
# Generates a new blog post from template + stdin content
# Usage: cat post-content.md | bash scripts/new-post.sh "Title" "slug" "2026-05-18" "Description"
#
# post-content.md format:
#   <!-- BODY -->
#   <p>Paragraph 1</p>
#   <p>Paragraph 2</p>
#   <!-- /BODY -->
#   <!-- CSS -->
#   <style>...</style>
#   <!-- /CSS -->

TITLE="${1:-Untitled}"
SLUG="${2:-untitled}"
DATE="${3:-$(date +%Y-%m-%d)}"
DESC="${4:-$TITLE}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$REPO_ROOT/scripts/templates/post.html"
OUTFILE="$REPO_ROOT/blog/$DATE-$SLUG.html"

if [[ ! -f "$TEMPLATE" ]]; then
    echo "ERROR: Template not found at $TEMPLATE" >&2
    exit 1
fi

# Read stdin
STDIN=$(cat)

# Extract body content
BODY=$(echo "$STDIN" | sed -n '/<!-- BODY -->/,/<!-- \/BODY -->/p' | sed '1d;$d')

# Extract custom CSS
CUSTOM_CSS=$(echo "$STDIN" | sed -n '/<!-- CSS -->/,/<!-- \/CSS -->/p' | sed '1d;$d')

# If no BODY marker, treat all stdin as body
if [[ -z "$BODY" ]]; then
    BODY="$STDIN"
fi

# Read template and substitute
TEMPLATE_CONTENT=$(cat "$TEMPLATE")

# Replace placeholders
OUTPUT="${TEMPLATE_CONTENT//TITLE/$TITLE}"
OUTPUT="${OUTPUT//SLUG/$SLUG}"
OUTPUT="${OUTPUT//DATE/$DATE}"
OUTPUT="${OUTPUT//DESCRIPTION/$DESC}"

# Replace body
if [[ -n "$BODY" ]]; then
    OUTPUT=$(echo "$OUTPUT" | sed "/<!-- BODY_START -->/,/<!-- BODY_END -->/c\\
    <!-- BODY_START -->\n$BODY\n    <!-- BODY_END -->")
fi

# Replace custom CSS
if [[ -n "$CUSTOM_CSS" ]]; then
    OUTPUT=$(echo "$OUTPUT" | sed "/<!-- CUSTOM_CSS_START -->/,/<!-- CUSTOM_CSS_END -->/c\\
    <!-- CUSTOM_CSS_START -->\n$CUSTOM_CSS\n    <!-- CUSTOM_CSS_END -->")
else
    OUTPUT=$(echo "$OUTPUT" | sed '/<!-- CUSTOM_CSS_START -->/,/<!-- CUSTOM_CSS_END -->/d')
fi

echo "$OUTPUT" > "$OUTFILE"
echo "✅ Created $OUTFILE"

# Run build
bash "$REPO_ROOT/scripts/build.sh"

echo ""
echo "Next: git add -A && git commit -m \"post: $TITLE\" && git push origin main"