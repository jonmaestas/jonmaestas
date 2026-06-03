#!/usr/bin/env bash
set -euo pipefail

# build.sh
# Regenerates blog/index.html and llms.txt from blog posts
# Run this after adding a new post

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BLOG_DIR="$REPO_ROOT/blog"
INDEX_FILE="$BLOG_DIR/index.html"
LLMS_FILE="$REPO_ROOT/llms.txt"
ROBOTS_FILE="$REPO_ROOT/robots.txt"
SITEMAP_FILE="$REPO_ROOT/sitemap.xml"
SITE_URL="https://jonmaestas.com"

# Extract metadata from a blog post
extract_meta() {
    local file="$1"
    local key="$2"
    perl -ne 'if (/<meta[^>]*name="'"$key"'"[^>]*content="([^"]+)"/) { print "$1\n"; exit }' "$file" 2>/dev/null || echo ""
}

extract_title() {
    local file="$1"
    local title
    title=$(perl -ne 'if (/<title>([^<]+)/) { print "$1\n"; exit }' "$file" 2>/dev/null | sed 's/ — Jon Maestas//')
    echo "${title:-Untitled}"
}

extract_date() {
    local file="$1"
    perl -ne 'if (/<p[^>]*>(\d{4}-\d{2}-\d{2})<\//) { print "$1\n"; exit }' "$file" 2>/dev/null || echo ""
}

# --- Generate blog/index.html ---
cat > "$INDEX_FILE" << 'HTML_HEAD'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Blog — Jon Maestas</title>
  <link rel="stylesheet" href="../index.css?v=20251007">
  <meta name="description" content="Posts, notes, and experiments from Jon Maestas.">
</head>
<body>
  <main>
    <header>
      <p class="post-meta"><a href="../index.html">← Home</a></p>
      <h1>Blog</h1>
      <p>Product updates, experiments, and notes on building things.</p>
    </header>

    <section id="posts">
      <ul class="post-list">
HTML_HEAD

# Find all blog posts, sort by filename (date-descending)
posts=()
while IFS= read -r -d '' file; do
    posts+=("$file")
done < <(find "$BLOG_DIR" -maxdepth 1 -name '*.html' ! -name 'index.html' -print0 | sort -rz)

# --- Generate robots.txt ---
cat > "$ROBOTS_FILE" << ROBOTS
User-agent: *
Allow: /

Sitemap: $SITE_URL/sitemap.xml
ROBOTS

for post in "${posts[@]}"; do
    filename=$(basename "$post")
    title=$(extract_title "$post")
    date=$(extract_date "$post")
    desc=$(extract_meta "$post" "description")
    echo "        <li>" >> "$INDEX_FILE"
    echo "          <a href=\"$filename\">$title</a>" >> "$INDEX_FILE"
    if [[ -n "$date" ]]; then
        echo "          <span class=\"post-date\">$date</span>" >> "$INDEX_FILE"
    fi
    if [[ -n "$desc" ]]; then
        echo "          <p class=\"post-excerpt\">$desc</p>" >> "$INDEX_FILE"
    fi
    echo "        </li>" >> "$INDEX_FILE"
done

cat >> "$INDEX_FILE" << 'HTML_FOOT'
      </ul>
    </section>

    <footer>
      <small><em>Made by Jon</em></small>
    </footer>
  </main>
</body>
</html>
HTML_FOOT

# --- Generate llms.txt ---
cat > "$LLMS_FILE" << 'LLMS_HEAD'
# llms.txt
# https://jonmaestas.com
# A machine-readable overview of this site for LLMs and AI crawlers.

## About

Jon Maestas is a software engineer and builder based in Missouri.
He runs SmopLab LLC, building AI-powered sports coaching apps and local community tools.

## Projects

- Player 1 Training (https://player1training.com) — AI sports coaching for youth athletes
- Westplex Country Store (https://westplexcountrystore.com) — Tradio app connected to KWRE radio
- Game Day Status (https://gamedaystatus.com) — Sports event status displays
- Wright City Sports (https://wrightcitysports.org) — Local sports community hub

## Blog Posts

LLMS_HEAD

for post in "${posts[@]}"; do
    filename=$(basename "$post")
    title=$(extract_title "$post")
    date=$(extract_date "$post")
    desc=$(extract_meta "$post" "description")
    url="https://jonmaestas.com/blog/$filename"
    echo "- [$title]($url)" >> "$LLMS_FILE"
    if [[ -n "$date" ]]; then
        echo "  Date: $date" >> "$LLMS_FILE"
    fi
    if [[ -n "$desc" ]]; then
        echo "  Summary: $desc" >> "$LLMS_FILE"
    fi
    echo "" >> "$LLMS_FILE"
done

cat >> "$LLMS_FILE" << 'LLMS_FOOT'
## Contact

- Email: jon@jonmaestas.com
- LinkedIn: https://www.linkedin.com/in/jonmaestas/
- GitHub: https://github.com/jonmaestas

## For AI Crawlers

This site is intentionally simple: static HTML, semantic markup, JSON-LD structured data.
All blog posts include `<meta name="description">`, Open Graph tags, and Schema.org BlogPosting markup.
Content is linkable, permanent, and free of paywalls or authentication.
LLMS_FOOT

# --- Generate sitemap.xml ---
today=$(date -u +%Y-%m-%d)
cat > "$SITEMAP_FILE" << SITEMAP_HEAD
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>$SITE_URL/</loc>
    <lastmod>$today</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>$SITE_URL/blog/</loc>
    <lastmod>$today</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>$SITE_URL/llms.txt</loc>
    <lastmod>$today</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.6</priority>
  </url>
SITEMAP_HEAD

for post in "${posts[@]}"; do
    filename=$(basename "$post")
    date=$(extract_date "$post")
    if [[ -z "$date" ]]; then
        date="$today"
    fi
    cat >> "$SITEMAP_FILE" << SITEMAP_URL
  <url>
    <loc>$SITE_URL/blog/$filename</loc>
    <lastmod>$date</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>
SITEMAP_URL
done

cat >> "$SITEMAP_FILE" << 'SITEMAP_FOOT'
</urlset>
SITEMAP_FOOT

echo "✅ Generated $INDEX_FILE"
echo "✅ Generated $LLMS_FILE"
echo "✅ Generated $ROBOTS_FILE"
echo "✅ Generated $SITEMAP_FILE"
echo ""
echo "Posts found: ${#posts[@]}"
