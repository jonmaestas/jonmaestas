#!/usr/bin/env python3
"""Build jonmaestas.com (static, served by GitHub Pages).

Inputs
  data/site.json               every product, link, and bio fact (single source of truth)
  scripts/templates/*.html     page templates; {{name}} slots are filled here
  blog/YYYY-MM-DD-slug.html    posts; only the text between the BODY_* and CUSTOM_CSS_*
                               markers, the <title>, and the meta description are read
  index.css                    site stylesheet (cache-busted by content hash)

Outputs
  index.html, about/index.html, 404.html, blog/index.html, blog/feed.xml,
  every post re-rendered from scripts/templates/post.html,
  llms.txt, llms-full.txt, sitemap.xml, robots.txt

Usage
  python3 scripts/build.py
  python3 scripts/build.py new-post "Title" slug YYYY-MM-DD "Description" < content.html
"""

import datetime
import hashlib
import html
import json
import math
import re
import subprocess
import sys
from email.utils import format_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "scripts" / "templates"
BLOG = ROOT / "blog"
DATA = json.loads((ROOT / "data" / "site.json").read_text(encoding="utf-8"))
SITE = DATA["site"]["url"].rstrip("/")
PERSON = DATA["person"]
ORG = DATA["organization"]
TODAY = datetime.date.today()
OG_IMAGE = f"{SITE}/images/og.png"
OG_ALT = "Jon Maestas: Player 1, Diamond Setup, Reindeer Food Co. and free tools for coaches."
PERSON_ID = f"{SITE}/#person"
ORG_ID = f"{SITE}/#smoplab"
WEBSITE_ID = f"{SITE}/#website"
POST_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.html$")
SLOT = re.compile(r"\{\{(\w+)\}\}")
UNTRACKED_HOSTS = ("apps.apple.com", "buy.stripe.com", "jonmaestas.com", "youtube.com")


def live(items):
    return [i for i in items if i.get("live", True)]


APPS = DATA["apps"]
P1 = next(a for a in APPS if a["id"] == "player-1")
SHOP = DATA["shop"]
HOLIDAY = live(DATA["holiday"])
TOOLS = DATA["tools"]
UTILITIES = DATA["utilities"]
GUIDES = DATA["guides"]
COMMUNITY = DATA["community"]
SERVICES = DATA["services"]


# ---------------------------------------------------------------- helpers

def e(text):
    return html.escape(str(text), quote=True)


def absolute(url):
    return url if url.startswith(("http://", "https://", "mailto:")) else SITE + url


def domain(url):
    return urlsplit(url).netloc.removeprefix("www.")


def tracked(url, slot):
    """Outbound link with UTM tags, so each destination's analytics can credit this site."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.netloc.endswith(UNTRACKED_HOSTS):
        return url
    query = parse_qsl(parts.query, keep_blank_values=True)
    utm = parse_qsl(DATA["site"]["utm"]) + [("utm_content", slot)]
    if parts.netloc == "play.google.com":
        query.append(("referrer", urlencode(utm)))
    else:
        query += utm
    return urlunsplit(parts._replace(query=urlencode(query)))


def fill(template, **values):
    def sub(match):
        key = match.group(1)
        if key not in values:
            sys.exit(f"build: template slot {{{{{key}}}}} has no value")
        return str(values[key])

    return SLOT.sub(sub, template)


def template(name):
    return (TEMPLATES / name).read_text(encoding="utf-8")


def jsonld(data):
    text = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return f'<script type="application/ld+json">\n{text}\n</script>'


def write(path, text):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
        print(f"  wrote {path.relative_to(ROOT)}")


def git_lastmod(*paths):
    """Last commit date touching any of paths; today if any of them has uncommitted edits."""
    rel = [str(p) for p in paths]
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *rel], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        return TODAY.isoformat()
    out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", *rel], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    return out or TODAY.isoformat()


def human_date(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"


def price_label(price):
    return "Free" if float(price) == 0 else f"${price}"


def css_version():
    return hashlib.sha1((ROOT / "index.css").read_bytes()).hexdigest()[:10]


# ---------------------------------------------------------------- posts

class Post:
    def __init__(self, path):
        self.path = path
        match = POST_FILE.match(path.name)
        self.date, self.slug = match.group(1), match.group(2)
        self.url = f"{SITE}/blog/{path.name}"
        self.href = f"/blog/{path.name}"
        source = path.read_text(encoding="utf-8")
        title = re.search(r"<title>(.*?)</title>", source, re.S)
        if not title:
            sys.exit(f"build: {path.name} has no <title>")
        self.title = html.unescape(title.group(1)).strip().removesuffix("— Jon Maestas").strip()
        desc = re.search(r'<meta\s+name="description"\s+content="(.*?)"\s*/?>', source, re.S)
        self.description = html.unescape(desc.group(1)).strip() if desc else self.title
        self.body = between(source, "BODY", path)
        self.custom_css = between(source, "CUSTOM_CSS", path, required=False)
        self.minutes = max(1, math.ceil(len(visible_text(self.body).split()) / 225))


def between(source, marker, path, required=True):
    match = re.search(rf"<!-- {marker}_START -->(.*?)<!-- {marker}_END -->", source, re.S)
    if match:
        return match.group(1)
    if required:
        sys.exit(f"build: {path.name} is missing <!-- {marker}_START --> / <!-- {marker}_END -->")
    return "\n"


def visible_text(fragment):
    fragment = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def load_posts():
    files = [p for p in BLOG.glob("*.html") if POST_FILE.match(p.name)]
    return sorted((Post(p) for p in files), key=lambda p: p.path.name, reverse=True)


# ---------------------------------------------------------------- shared chrome

GLYPHS = {
    "timer": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5M9 2h6M12 2v3"/></svg>',
    "ball": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m12 7 4.2 3-1.6 5H9.4L7.8 10z"/><path d="M12 7V3M16.2 10l3.9-1.3M14.6 15l2.4 3.4M9.4 15 7 18.4M7.8 10 3.9 8.7"/></svg>',
    "arrow": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    "mail": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    "radio": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="8" width="18" height="12" rx="2"/><path d="M7 8 17 3"/><circle cx="15.5" cy="14" r="2.5"/><path d="M6.5 12.5h4M6.5 15.5h4"/></svg>',
    "spark": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/></svg>',
    "flag": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 21V4M5 4h11l-2 4 2 4H5"/></svg>',
    "book": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5M8 7h7"/></svg>',
    "board": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/><circle cx="12" cy="12" r="3"/></svg>',
    "trophy": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M17 5h3v2a3 3 0 0 1-3 3M7 5H4v2a3 3 0 0 0 3 3"/></svg>',
    "qr": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 14h3v3h-3zM20 14v.01M17 20h4M20 17v3"/></svg>',
}


def glyph(name):
    return f'<span class="glyph">{GLYPHS[name]}</span>'


def common_head():
    v = css_version()
    return "\n".join([
        f'<link rel="stylesheet" href="/index.css?v={v}">',
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
        '<meta name="theme-color" content="#fafafa" media="(prefers-color-scheme: light)">',
        '<meta name="theme-color" content="#09090b" media="(prefers-color-scheme: dark)">',
        f'<link rel="alternate" type="application/rss+xml" title="Jon Maestas: Writing" href="{SITE}/blog/feed.xml">',
        f'<link rel="alternate" type="text/plain" title="llms.txt" href="{SITE}/llms.txt">',
        f'<meta property="og:site_name" content="{e(DATA["site"]["name"])}">',
        '<meta property="og:locale" content="en_US">',
        f'<meta property="og:image" content="{OG_IMAGE}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{e(OG_ALT)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:site" content="{e(DATA["site"]["twitter"])}">',
        f'<meta name="twitter:creator" content="{e(DATA["site"]["twitter"])}">',
        f'<meta name="twitter:image" content="{OG_IMAGE}">',
        f'<meta name="author" content="{e(PERSON["name"])}">',
    ])


def page_head(title, description, path, graph, og_type="website", noindex=False):
    url = SITE + path
    robots = "noindex, follow" if noindex else "index, follow, max-image-preview:large, max-snippet:-1"
    return "\n".join([
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(title)}</title>",
        f'<meta name="description" content="{e(description)}">',
        f'<meta name="robots" content="{robots}">',
        f'<link rel="canonical" href="{url}">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(description)}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta name="twitter:title" content="{e(title)}">',
        f'<meta name="twitter:description" content="{e(description)}">',
        common_head(),
        jsonld({"@context": "https://schema.org", "@graph": graph}) if graph else "",
    ])


def site_header():
    nav = [("/#apps", "Apps"), ("/#shop", "Shop"), ("/#tools", "Free tools"),
           ("/#guides", "Guides"), ("/blog/", "Writing"), ("/about/", "About")]
    links = "".join(f'<a href="{href}">{label}</a>' for href, label in nav)
    return f"""<a class="skip-link" href="#main">Skip to content</a>
<header class="site-header">
  <div class="wrap header-inner">
    <a class="brand" href="/"><img src="/favicon.svg" width="28" height="28" alt=""><span>Jon Maestas</span></a>
    <nav class="site-nav" aria-label="Main">{links}</nav>
    <a class="btn btn-primary btn-sm header-cta" href="{e(tracked(P1["url"], "header"))}">Get Player 1</a>
  </div>
</header>"""


def site_footer():
    def column(title, items):
        lis = "".join(f'<li><a href="{e(href)}">{e(label)}</a></li>' for label, href in items)
        return f'<div><h2 class="footer-title">{e(title)}</h2><ul>{lis}</ul></div>'

    apps = [(a["name"], tracked(a["url"], "footer")) for a in APPS]
    shop = [(s["name"], tracked(s["url"], "footer")) for s in SHOP + HOLIDAY]
    tools = [(t["name"], t["url"]) for t in TOOLS + UTILITIES]
    company = [(ORG["name"], tracked(ORG["url"], "footer"))] + \
              [(s["name"], tracked(s["url"], "footer")) for s in SERVICES if s["url"] != ORG["url"]] + \
              [(c["name"], tracked(c["url"], "footer")) for c in COMMUNITY]
    site = [("Writing", "/blog/"), ("About", "/about/"), ("Email Jon", f"mailto:{PERSON['email']}")] + \
           [(l["name"], l["url"]) for l in PERSON["links"]] + \
           [("RSS", "/blog/feed.xml"), ("llms.txt", "/llms.txt")]
    return f"""<footer class="site-footer">
  <div class="wrap footer-grid">
    {column("Apps", apps)}
    {column("Shop", shop)}
    {column("Free tools", tools)}
    {column("Projects", company)}
    {column("Jon Maestas", site)}
  </div>
  <div class="wrap footer-base">
    <p>© {TODAY.year} Jon Maestas · {e(ORG["name"])} · {e(ORG["location"])}</p>
  </div>
</footer>"""


def store_badges(app, slot):
    out = []
    if app.get("appStore"):
        out.append(f'<a class="store-badge" href="{e(app["appStore"])}"><img src="/images/badges/app-store.svg" '
                   f'width="120" height="40" alt="Download {e(app["shortName"])} on the App Store"></a>')
    if app.get("googlePlay"):
        out.append(f'<a class="store-badge" href="{e(tracked(app["googlePlay"], slot))}"><img src="/images/badges/google-play.png" '
                   f'width="134" height="40" alt="Get {e(app["shortName"])} on Google Play"></a>')
    return f'<div class="store-badges">{"".join(out)}</div>'


def post_cta():
    return f"""<aside class="post-cta card" aria-label="Player 1">
  <img class="app-icon" src="{P1["icon"]}" width="64" height="64" alt="" loading="lazy">
  <div>
    <p class="eyebrow">What I build</p>
    <h2>Player 1 is a free AI sports coach on your phone.</h2>
    <p>Record a rep, get feedback in seconds on what to keep and what to fix next. 13 sports, no sensors.</p>
    {store_badges(P1, "post-cta")}
    <p class="small"><a href="/#apps">More apps and tools I build</a></p>
  </div>
</aside>"""


def post_items(posts, heading="h3"):
    items = []
    for p in posts:
        items.append(f"""<li>
  <{heading} class="post-title"><a href="{p.href}">{e(p.title)}</a></{heading}>
  <p class="post-meta"><time datetime="{p.date}">{human_date(p.date)}</time> · {p.minutes} min read</p>
  <p class="post-excerpt">{e(p.description)}</p>
</li>""")
    return f'<ul class="post-list">{"".join(items)}</ul>'


# ---------------------------------------------------------------- structured data

def person_ld():
    return {
        "@type": "Person",
        "@id": PERSON_ID,
        "name": PERSON["name"],
        "url": SITE + "/",
        "email": f"mailto:{PERSON['email']}",
        "jobTitle": PERSON["jobTitle"],
        "description": PERSON["summary"],
        "worksFor": {"@id": ORG_ID},
        "homeLocation": {"@type": "Place", "name": PERSON["location"]},
        "alumniOf": {"@type": "CollegeOrUniversity", "name": PERSON["alumniOf"]},
        "knowsAbout": PERSON["knowsAbout"],
        "sameAs": PERSON["sameAs"],
    }


def org_ld():
    return {
        "@type": "Organization",
        "@id": ORG_ID,
        "name": ORG["name"],
        "url": ORG["url"],
        "email": f"mailto:{ORG['email']}",
        "founder": {"@id": PERSON_ID},
        "address": {"@type": "PostalAddress", "addressLocality": "Wright City",
                    "addressRegion": "MO", "addressCountry": "US"},
        "brand": [{"@type": "Brand", "name": "Player 1"}, {"@type": "Brand", "name": "Reindeer Food Co."}],
    }


def website_ld():
    return {
        "@type": "WebSite",
        "@id": WEBSITE_ID,
        "url": SITE + "/",
        "name": DATA["site"]["name"],
        "description": DATA["site"]["description"],
        "publisher": {"@id": PERSON_ID},
        "inLanguage": "en-US",
    }


def breadcrumb_ld(*crumbs):
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": name, "item": url}
                            for i, (name, url) in enumerate(crumbs)],
    }


def offer_ld(price, url=None):
    offer = {"@type": "Offer", "price": price, "priceCurrency": "USD"}
    if url:
        offer["url"] = url
    return offer


def app_ld(app):
    return {
        "@type": "MobileApplication",
        "@id": f"{SITE}/#{app['id']}",
        "name": app["name"],
        "alternateName": app.get("aliases", [app["shortName"]]),
        "description": f"{app['tagline']} {app['summary']}",
        "url": app["url"],
        "image": absolute(app["icon"]),
        "operatingSystem": app["operatingSystem"],
        "applicationCategory": app["category"],
        "downloadUrl": [u for u in (app.get("appStore"), app.get("googlePlay")) if u],
        "offers": offer_ld(app["price"]),
        "author": {"@id": PERSON_ID},
        "publisher": {"@id": ORG_ID},
        **({"sameAs": app["sameAs"]} if app.get("sameAs") else {}),
    }


def press_line(p):
    return (f"Featured on {p['outlet']} by {p['hosts']} in \"{p['segment']}\" "
            f"({human_date(p['date'])}, at {p['timestamp']}): {p['url']}")


def video_ld(p):
    return {
        "@type": "VideoObject",
        "name": f"{p['outlet']}: {p['episode']}",
        "description": f"{p['hosts']} feature Reindeer Food Co. at {p['timestamp']} in \"{p['segment']}\".",
        "uploadDate": p["date"],
        "thumbnailUrl": p["thumbnailRemote"],
        "url": p["url"],
        "publisher": {"@type": "Organization", "name": p["outlet"]},
    }


def shop_ld(shop):
    return {
        "@type": "OnlineStore",
        "@id": f"{SITE}/#{shop['id']}",
        "name": shop["name"],
        "url": shop["url"],
        "description": f"{shop['tagline']} {shop['madeByAbout']} {shop['summary']}",
        "image": absolute(shop["image"]),
        "parentOrganization": {"@id": ORG_ID},
        "makesOffer": [{"@type": "Offer", "name": o["name"], "price": o["price"], "priceCurrency": "USD"}
                       for o in shop["offers"]],
        "subjectOf": [video_ld(p) for p in shop.get("press", [])],
    }


def tool_ld(tool):
    return {
        "@type": "WebApplication",
        "@id": f"{SITE}/#{tool['id']}",
        "name": tool["name"],
        "url": absolute(tool["url"]),
        "description": tool["summary"],
        "applicationCategory": tool["category"],
        "operatingSystem": "Any (web browser)",
        "isAccessibleForFree": True,
        "offers": offer_ld("0"),
        "author": {"@id": PERSON_ID},
    }


def site_ld(item, kind="WebSite"):
    return {"@type": kind, "name": item["name"], "url": item["url"], "description": item["summary"],
            "creator": {"@id": PERSON_ID}}


def service_ld(service):
    return {"@type": "Service", "name": service["name"], "url": service["url"],
            "description": service["summary"], "provider": {"@id": ORG_ID}, "areaServed": "US"}


# ---------------------------------------------------------------- FAQ (home page + llms-full.txt)

def faq():
    diamond = next(a for a in APPS if a["id"] == "diamond-setup")
    reindeer = SHOP[0]
    radio = next(s for s in SERVICES if s["id"] == "radio-to-web")
    tool_names = ", ".join(t["name"] for t in TOOLS)
    utility_names = ", ".join(f"{u['name']} ({u['url']})" for u in UTILITIES)
    note = f" {reindeer['note']}" if TODAY.isoformat() <= reindeer["noteUntil"] else ""
    return [
        ("Who is Jon Maestas?", PERSON["summary"]),
        ("What apps has Jon Maestas built?",
         f"{P1['name']} ({P1['url']}), a free AI sports coach for iPhone and Android, and {diamond['name']} "
         f"({diamond['url']}), an AR baseball and softball field layout app for iPhone. He also makes free "
         f"web tools for coaches and players: {tool_names}, plus {utility_names} for moving text and files "
         f"between devices."),
        ("Is Player 1 free?", P1["pricing"]),
        ("What does Player 1: Diamond Setup do?", f"{diamond['summary']} {diamond['pricing']}"),
        ("Where can I buy Reindeer Food?", f"From Reindeer Food Co. at {reindeer['url']}. {reindeer['pricing']}{note}"),
        ("Who runs Reindeer Food Co.?",
         " ".join([reindeer["madeByAbout"]] + [press_line(p) for p in reindeer.get("press", [])])),
        ("Can SmopLab turn my radio show into a website?",
         f"Yes. {radio['summary']} Email {radio['email']}."),
        ("How do I contact Jon Maestas?",
         f"Email {PERSON['email']}, or find him on LinkedIn at {PERSON['sameAs'][0]}."),
    ]


def faq_ld():
    return {"@type": "FAQPage", "@id": f"{SITE}/#faq", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq()]}


def linkify(text):
    """Escape text, then turn bare URLs and emails into links."""
    out = e(text)
    out = re.sub(r"https?://[^\s,)]+[^\s,).]", lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', out)
    return re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.]+[a-z]\b", lambda m: f'<a href="mailto:{m.group(0)}">{m.group(0)}</a>', out)


# ---------------------------------------------------------------- home page

def hero_tiles():
    diamond = next(a for a in APPS if a["id"] == "diamond-setup")
    board = next(t for t in TOOLS if t["id"] == "soccer-board")
    tiles = [
        (P1["shortName"], "AI sports coach", P1["icon"], "#player-1"),
        (diamond["shortName"], "AR field layout", diamond["icon"], "#diamond-setup"),
        (SHOP[0]["name"], "Run by my kids", SHOP[0]["icon"], "#reindeer-food"),
        (board["name"], "Free tactics board", board["icon"], "#tools"),
    ]
    return "".join(f"""<a class="tile" href="{href}">
  <img src="{icon}" width="56" height="56" alt="">
  <span class="tile-name">{e(name)}</span>
  <span class="tile-label">{e(label)}</span>
</a>""" for name, label, icon, href in tiles)


def details_list(items):
    return "<ul class=\"checks\">" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>"


def render_apps():
    p1 = P1
    chips = "".join(f'<a class="chip" href="{e(tracked(s["url"], "sport-chip"))}">{e(s["name"])}</a>' for s in p1["sports"])
    cards = [f"""<article class="card featured" id="{p1['id']}">
  <div class="featured-main">
    <div class="product-head">
      <img class="app-icon" src="{p1['icon']}" width="72" height="72" alt="{e(p1['shortName'])} app icon">
      <div>
        <h3 class="product-name">{e(p1['name'])}</h3>
        <p class="product-tagline">{e(p1['tagline'])}</p>
      </div>
    </div>
    <p>{e(p1['summary'])}</p>
    <p class="pricing">{e(p1['pricing'])}</p>
    {store_badges(p1, "apps")}
    <p class="small"><a href="{e(tracked(p1['url'], 'apps'))}">{domain(p1['url'])}</a></p>
    {details_list(p1['details'])}
  </div>
  <div class="featured-side">
    <h4>AI coaching by sport</h4>
    <div class="chips">{chips}</div>
    <p class="small muted">Built by a dad who still films his kids' reps from the sideline. It works on adult golf swings too.</p>
  </div>
</article>"""]
    for app in APPS:
        if app is p1:
            continue
        badge = f'<span class="pill">{e(app["badge"])}</span>' if app.get("badge") else ""
        guide = f' · <a href="{e(tracked(app["guide"]["url"], "apps"))}">{e(app["guide"]["name"])}</a>' if app.get("guide") else ""
        cards.append(f"""<article class="card product" id="{app['id']}">
  <div class="product-main">
    <div class="product-head">
      <img class="app-icon" src="{app['icon']}" width="72" height="72" alt="{e(app['shortName'])} app icon" loading="lazy">
      <div>
        <h3 class="product-name">{e(app['name'])} {badge}</h3>
        <p class="product-tagline">{e(app['tagline'])}</p>
      </div>
    </div>
    <p>{e(app['summary'])}</p>
    <p class="pricing">{e(app['pricing'])}</p>
    {store_badges(app, "apps")}
    <p class="small"><a href="{e(tracked(app['url'], 'apps'))}">Product page</a>{guide}</p>
  </div>
  <div class="product-side">
    {details_list(app['details'])}
  </div>
</article>""")
    return "\n".join(cards)


def render_shop():
    out = []
    for shop in SHOP:
        offers = "".join(f"""<li><span>{e(o['name'])}</span><span class="price">${e(o['price'])}</span>
<a href="{e(o['url'])}">Buy</a></li>""" for o in shop["offers"])
        note = f'<p class="pill pill-festive">{e(shop["note"])}</p>' if TODAY.isoformat() <= shop["noteUntil"] else ""
        out.append(f"""<article class="card shop" id="{shop['id']}">
  <img class="shop-photo" src="{shop['image']}" srcset="{shop['imageSmall']} 480w, {shop['image']} 800w"
       sizes="(min-width: 860px) 360px, 100vw" width="800" height="952" alt="{e(shop['imageAlt'])}" loading="lazy">
  <div class="shop-body">
    <h3 class="product-name">{e(shop['name'])}</h3>
    <p class="made-by">{e(shop['madeBy'])}</p>
    <p>{e(shop['summary'])}</p>
    {note}
    <ul class="offers">{offers}</ul>
    <p class="small muted">Free US shipping on every order. Tax included.</p>
    <div class="cta-row">
      <a class="btn btn-primary" href="{e(tracked(shop['url'], 'shop'))}">Shop {domain(shop['url'])}</a>
      <a class="btn btn-ghost" href="{e(tracked(shop['recipe']['url'], 'shop'))}">{e(shop['recipe']['name'])}</a>
    </div>
    {render_press(shop.get('press', []))}
  </div>
</article>""")
    if HOLIDAY:
        cards = "".join(f"""<a class="card mini" href="{e(tracked(h['url'], 'holiday'))}">
  <span class="mini-name">{e(h['name'])}</span><span class="mini-domain">{domain(h['url'])}</span>
  <span class="mini-summary">{e(h['summary'])}</span>
</a>""" for h in HOLIDAY)
        out.append(f'<h3 class="subhead">More Christmas from Reindeer Food Co.</h3><div class="grid grid-mini">{cards}</div>')
    return "\n".join(out)


def render_press(press):
    return "".join(f"""<a class="press" href="{e(p['url'])}">
  <img src="{p['thumbnail']}" width="160" height="90" alt="" loading="lazy">
  <span class="press-text">
    <span class="press-label">Featured on {e(p['outlet'])}</span>
    <span class="press-title">{e(p['hosts'])}: “{e(p['segment'])}”</span>
    <span class="press-meta">Watch the segment at {e(p['timestamp'])}</span>
  </span>
</a>""" for p in press)


def render_tools():
    cards = []
    for t in TOOLS:
        icon = f'<img src="{t["icon"]}" width="48" height="48" alt="" loading="lazy">' if t.get("icon") else glyph(t["glyph"])
        cards.append(f"""<a class="card tool" href="{t['url']}">
  <span class="tool-icon">{icon}</span>
  <span class="tool-name">{e(t['name'])}</span>
  <span class="tool-summary">{e(t['summary'])}</span>
  <span class="tool-open">Open {GLYPHS['arrow']}</span>
</a>""")
    return f'<div class="grid grid-tools">{"".join(cards)}</div>{render_utilities()}'


def render_utilities():
    cards = []
    for u in UTILITIES:
        links = "".join(f'<li><a href="{e(l["url"])}">{e(l["name"])}</a><p>{e(l["summary"])}</p></li>' for l in u["links"])
        cards.append(f"""<article class="card utility" id="{u['id']}">
  <div>
    <div class="utility-head">
      {glyph(u['glyph'])}
      <div>
        <h4 class="tool-name"><a href="{e(u['url'])}">{e(u['name'])}</a></h4>
        <span class="mini-domain">{domain(u['url'])}</span>
      </div>
    </div>
    <p class="tool-summary">{e(u['summary'])}</p>
  </div>
  <ul class="utility-links">{links}</ul>
</article>""")
    return f'<h3 class="subhead">Everyday tools</h3><div class="stack">{"".join(cards)}</div>' if cards else ""


def render_guides():
    groups = []
    for g in GUIDES:
        items = "".join(f"""<li><a href="{e(tracked(s['url'], 'guides'))}"><span class="guide-name">{e(s['name'])}</span>
<span class="guide-domain">{domain(s['url'])}</span></a><p>{e(s['summary'])}</p></li>""" for s in g["sites"])
        groups.append(f'<div class="guide-group"><h3>{e(g["group"])}</h3><ul>{items}</ul></div>')
    return f'<div class="guide-groups">{"".join(groups)}</div>'


def render_community():
    icons = {"wright-city-sports": "trophy", "coachs-playbook": "book", "game-day-status": "board"}
    cards = "".join(f"""<a class="card mini" href="{e(tracked(c['url'], 'community'))}">
  {glyph(icons.get(c['id'], 'flag'))}
  <span class="mini-name">{e(c['name'])}</span><span class="mini-domain">{domain(c['url'])}</span>
  <span class="mini-summary">{e(c['summary'])}</span>
</a>""" for c in COMMUNITY)
    return f'<div class="grid grid-mini">{cards}</div>'


def render_services():
    icons = {"radio-to-web": "radio", "smoplab": "spark"}
    cards = []
    for s in SERVICES:
        details = details_list(s["details"]) if s.get("details") else ""
        cards.append(f"""<article class="card service" id="{s['id']}">
  {glyph(icons.get(s['id'], 'spark'))}
  <h3 class="product-name">{e(s['name'])}</h3>
  <p>{e(s['summary'])}</p>
  {details}
  <div class="cta-row">
    <a class="btn btn-primary" href="mailto:{e(s['email'])}">{GLYPHS['mail']} {e(s['email'])}</a>
    <a class="btn btn-ghost" href="{e(tracked(s['url'], 'services'))}">{domain(s['url'])}</a>
  </div>
</article>""")
    return f'<div class="grid grid-services">{"".join(cards)}</div>'


def render_faq():
    return "".join(f"""<details>
  <summary>{e(q)}</summary>
  <p>{linkify(a)}</p>
</details>""" for q, a in faq())


def build_home(posts):
    graph = [website_ld(), person_ld(), org_ld(),
             {"@type": "WebPage", "@id": f"{SITE}/#webpage", "url": SITE + "/", "name": DATA["site"]["title"],
              "description": DATA["site"]["description"], "isPartOf": {"@id": WEBSITE_ID},
              "about": {"@id": PERSON_ID}, "primaryImageOfPage": OG_IMAGE, "inLanguage": "en-US"},
             *[app_ld(a) for a in APPS], *[shop_ld(s) for s in SHOP], *[tool_ld(t) for t in TOOLS + UTILITIES],
             *[site_ld(h) for h in HOLIDAY], *[site_ld(c) for c in COMMUNITY], *[service_ld(s) for s in SERVICES],
             {"@type": "ItemList", "@id": f"{SITE}/#guides", "name": "Free coaching guides",
              "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": s["name"], "url": s["url"]}
                                  for i, s in enumerate(s for g in GUIDES for s in g["sites"])]},
             faq_ld()]
    head = page_head(DATA["site"]["title"], DATA["site"]["description"], "/", graph)
    page = fill(template("home.html"), head=head, header=site_header(), footer=site_footer(),
                hero_tiles=hero_tiles(), p1_cta=e(tracked(P1["url"], "hero")), apps=render_apps(),
                shop=render_shop(), tools=render_tools(), guides=render_guides(),
                guide_count=sum(len(g["sites"]) for g in GUIDES), community=render_community(),
                services=render_services(), posts=post_items(posts[:3]), faq=render_faq(),
                email=e(PERSON["email"]))
    write("index.html", page)


# ---------------------------------------------------------------- other pages

def build_about():
    title = "About Jon Maestas: Builder, Parent-Coach, Founder of SmopLab"
    description = ("Jon Maestas is a software builder and parent-coach in Wright City, Missouri, founder of SmopLab LLC, "
                   "and the maker of Player 1 and Diamond Setup. His kids created and operate Reindeer Food Co.")
    graph = [website_ld(), person_ld(), org_ld(),
             {"@type": "ProfilePage", "@id": f"{SITE}/about/#page", "url": f"{SITE}/about/", "name": title,
              "description": description, "isPartOf": {"@id": WEBSITE_ID}, "mainEntity": {"@id": PERSON_ID}},
             breadcrumb_ld(("Home", SITE + "/"), ("About", f"{SITE}/about/"))]
    bio = "".join(f"<p>{e(p)}</p>" for p in PERSON["bio"])
    built = [(a["name"], tracked(a["url"], "about"), a["tagline"]) for a in APPS] + \
            [(s["name"], tracked(s["url"], "about"), f"{s['tagline']} {s['madeBy']}") for s in SHOP] + \
            [(h["name"], tracked(h["url"], "about"), h["summary"]) for h in HOLIDAY] + \
            [(t["name"], t["url"], t["summary"]) for t in TOOLS + UTILITIES] + \
            [(c["name"], tracked(c["url"], "about"), c["summary"]) for c in COMMUNITY] + \
            [(s["name"], tracked(s["url"], "about"), s["summary"]) for s in SERVICES]
    built_html = "".join(f'<li><a href="{e(u)}">{e(n)}</a>: {e(d)}</li>' for n, u, d in built)
    facts = [("Lives in", PERSON["location"]), ("Company", f'<a href="{e(tracked(ORG["url"], "about"))}">{e(ORG["name"])}</a>'),
             ("College", f"{e(PERSON['alumniOf'])}, on a baseball scholarship"),
             ("Email", f'<a href="mailto:{e(PERSON["email"])}">{e(PERSON["email"])}</a>'),
             ("Elsewhere", " · ".join(f'<a href="{e(l["url"])}">{e(l["name"])}</a>' for l in PERSON["links"]))]
    facts_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)
    page = fill(template("about.html"), head=page_head(title, description, "/about/", graph, og_type="profile"),
                header=site_header(), footer=site_footer(), bio=bio, built=built_html, facts=facts_html,
                guide_count=sum(len(g["sites"]) for g in GUIDES), cta=post_cta())
    write("about/index.html", page)


def build_blog_index(posts):
    title = "Writing: Jon Maestas on Building in Public, AI and Athletic Intelligence"
    description = ("Notes from Jon Maestas on building Player 1 in public, AI agents, Athletic Intelligence, "
                   "and shipping real products from Wright City, Missouri.")
    graph = [website_ld(), person_ld(),
             {"@type": "Blog", "@id": f"{SITE}/blog/#blog", "url": f"{SITE}/blog/", "name": "Jon Maestas: Writing",
              "description": description, "author": {"@id": PERSON_ID}, "publisher": {"@id": PERSON_ID},
              "blogPost": [{"@type": "BlogPosting", "headline": p.title, "url": p.url, "datePublished": p.date,
                            "description": p.description} for p in posts]},
             breadcrumb_ld(("Home", SITE + "/"), ("Writing", f"{SITE}/blog/"))]
    page = fill(template("blog-index.html"), head=page_head(title, description, "/blog/", graph),
                header=site_header(), footer=site_footer(), posts=post_items(posts, "h2"), cta=post_cta())
    write("blog/index.html", page)


def build_404():
    links = [(a["name"], tracked(a["url"], "404")) for a in APPS] + \
            [(s["name"], tracked(s["url"], "404")) for s in SHOP] + \
            [(t["name"], t["url"]) for t in TOOLS] + [("Writing", "/blog/"), ("About", "/about/")]
    items = "".join(f'<li><a href="{e(u)}">{e(n)}</a></li>' for n, u in links)
    page = fill(template("404.html"), head=page_head("Page not found: Jon Maestas", "This page doesn't exist.", "/404.html", None, noindex=True),
                header=site_header(), footer=site_footer(), links=items)
    write("404.html", page)


def render_post(post, newer, older):
    def token(match):
        return {"TITLE": e(post.title), "DESCRIPTION": e(post.description),
                "DATE": post.date, "SLUG": e(post.slug)}[match.group(0)]

    graph = [{
        "@type": "BlogPosting",
        "@id": f"{post.url}#post",
        "headline": post.title,
        "description": post.description,
        "datePublished": post.date,
        "url": post.url,
        "mainEntityOfPage": post.url,
        "image": OG_IMAGE,
        "inLanguage": "en-US",
        "author": {"@type": "Person", "@id": PERSON_ID, "name": PERSON["name"], "url": SITE + "/"},
        "publisher": {"@id": PERSON_ID},
        "isPartOf": {"@id": f"{SITE}/blog/#blog"},
    }, breadcrumb_ld(("Home", SITE + "/"), ("Writing", f"{SITE}/blog/"), (post.title, post.url))]
    nav = []
    if older:
        nav.append(f'<a class="post-nav-older" href="{older.href}"><span class="small muted">Older</span>{e(older.title)}</a>')
    if newer:
        nav.append(f'<a class="post-nav-newer" href="{newer.href}"><span class="small muted">Newer</span>{e(newer.title)}</a>')
    chrome = re.sub(r"\b(TITLE|DESCRIPTION|DATE|SLUG)\b", token, template("post.html"))
    page = fill(chrome, common_head=common_head(), post_jsonld=jsonld({"@context": "https://schema.org", "@graph": graph}),
                header=site_header(), footer=site_footer(), date_human=human_date(post.date),
                minutes=post.minutes, post_cta=post_cta(), post_nav=f'<nav class="post-nav" aria-label="More writing">{"".join(nav)}</nav>')
    for marker, content in (("CUSTOM_CSS", post.custom_css), ("BODY", post.body)):
        page = re.sub(rf"<!-- {marker}_START -->.*?<!-- {marker}_END -->",
                      lambda _: f"<!-- {marker}_START -->{content}<!-- {marker}_END -->", page, count=1, flags=re.S)
    write(f"blog/{post.path.name}", page)


def build_posts(posts):
    for i, post in enumerate(posts):
        render_post(post, posts[i - 1] if i > 0 else None, posts[i + 1] if i + 1 < len(posts) else None)


def build_feed(posts):
    items = []
    for p in posts:
        pub = datetime.datetime.fromisoformat(p.date + "T12:00:00+00:00")
        items.append(f"""    <item>
      <title>{e(p.title)}</title>
      <link>{p.url}</link>
      <guid isPermaLink="true">{p.url}</guid>
      <pubDate>{format_datetime(pub)}</pubDate>
      <description>{e(p.description)}</description>
    </item>""")
    newest = datetime.datetime.fromisoformat((posts[0].date if posts else TODAY.isoformat()) + "T12:00:00+00:00")
    write("blog/feed.xml", f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Jon Maestas: Writing</title>
    <link>{SITE}/blog/</link>
    <atom:link href="{SITE}/blog/feed.xml" rel="self" type="application/rss+xml"/>
    <description>Building Player 1 in public, AI agents, and Athletic Intelligence.</description>
    <language>en-us</language>
    <lastBuildDate>{format_datetime(newest)}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
""")


# ---------------------------------------------------------------- crawler files

def build_robots():
    write("robots.txt", f"""# jonmaestas.com welcomes every crawler, including AI search engines and assistants.
# Summary for language models: {SITE}/llms.txt
# Full detail for language models: {SITE}/llms-full.txt
User-agent: *
Content-Signal: search=yes, ai-input=yes, ai-train=yes
Allow: /

Sitemap: {SITE}/sitemap.xml
""")


def build_sitemap(posts):
    newest = posts[0].date if posts else TODAY.isoformat()
    home = max(git_lastmod("data/site.json", "scripts/templates/home.html", "index.css"), newest)
    urls = [(f"{SITE}/", home),
            (f"{SITE}/about/", git_lastmod("data/site.json", "scripts/templates/about.html")),
            (f"{SITE}/blog/", max(git_lastmod("scripts/templates/blog-index.html"), newest))]
    urls += [(p.url, p.date) for p in posts]
    for t in TOOLS:
        path = t["url"].lstrip("/") or "index.html"
        path = path + "index.html" if path.endswith("/") else path
        urls.append((absolute(t["url"]), git_lastmod(path)))
    body = "\n".join(f"  <url>\n    <loc>{e(loc)}</loc>\n    <lastmod>{mod}</lastmod>\n  </url>" for loc, mod in urls)
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n'
                         f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n')


def llms_intro():
    return (f"> {PERSON['summary']}")


def build_llms(posts):
    lines = [f"# {PERSON['name']}", "", llms_intro(), "",
             f"This file summarizes {domain(SITE)} for AI assistants. The detailed version, with every product, "
             f"price, FAQ answer and the full text of every blog post, is at {SITE}/llms-full.txt.", ""]

    lines += ["## Apps", ""]
    for a in APPS:
        stores = "; ".join(f"{k}: {a[f]}" for k, f in (("App Store", "appStore"), ("Google Play", "googlePlay")) if a.get(f))
        lines.append(f"- [{a['name']}]({a['url']}): {a['tagline']} {a['summary']} {a['pricing']} {stores}")
    lines += ["", "## Shop", ""]
    for s in SHOP:
        press = " ".join(press_line(p) for p in s.get("press", []))
        lines.append(f"- [{s['name']}]({s['url']}): {s['tagline']} {s['madeByAbout']} {s['summary']} {s['pricing']} {press}")
    for h in HOLIDAY:
        lines.append(f"- [{h['name']}]({h['url']}): {h['summary']}")
    lines += ["", "## Free web tools", ""]
    lines += [f"- [{t['name']}]({absolute(t['url'])}): {t['summary']}" for t in TOOLS]
    for u in UTILITIES:
        parts = "; ".join(f"[{l['name']}]({l['url']}): {l['summary']}" for l in u["links"])
        lines.append(f"- [{u['name']}]({u['url']}): {u['summary']} {parts}")
    lines += ["", "## Free coaching guides", ""]
    for g in GUIDES:
        lines += [f"- [{s['name']}]({s['url']}) ({g['group']}): {s['summary']}" for s in g["sites"]]
    lines += ["", "## Community", ""]
    lines += [f"- [{c['name']}]({c['url']}): {c['summary']}" for c in COMMUNITY]
    lines += ["", f"## Work with {ORG['name']}", ""]
    lines += [f"- [{s['name']}]({s['url']}): {s['summary']} Contact: {s['email']}" for s in SERVICES]
    lines += ["", "## Writing", ""]
    lines += [f"- [{p.title}]({p.url}): {p.description} ({p.date})" for p in posts]
    lines += ["", "## About", "",
              f"- [About Jon Maestas]({SITE}/about/): bio, background and everything he builds.",
              f"- Email: {PERSON['email']}"]
    lines += [f"- {l['name']}: {l['url']}" for l in PERSON["links"]]
    lines += ["", "## Optional", "",
              f"- [llms-full.txt]({SITE}/llms-full.txt): every product in detail, the FAQ, and the full text of every post.",
              f"- [RSS feed]({SITE}/blog/feed.xml)",
              f"- [Sitemap]({SITE}/sitemap.xml)", ""]
    write("llms.txt", "\n".join(lines))


class Markdown(HTMLParser):
    """Small HTML-to-Markdown converter for post bodies (headings, paragraphs, lists, links, code, quotes, tables)."""

    SKIP = {"script", "style", "svg", "noscript", "button", "canvas", "select", "form"}
    BLOCKS = {"p", "div", "section", "article", "figure", "figcaption", "header", "footer", "table", "aside"}

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.stack = [[]]
        self.hrefs = []
        self.lists = []
        self.skip = 0
        self.pre = 0
        self.cells = 0

    def emit(self, text):
        self.stack[-1].append(text)

    def newline(self, count=1):
        self.emit("\n" * count)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        attrs = dict(attrs)
        if tag in self.BLOCKS:
            self.newline(2)
        elif re.fullmatch(r"h[1-6]", tag):
            self.newline(2)
            self.emit("#" * min(6, int(tag[1]) + 2) + " ")
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
            self.newline(1 if len(self.lists) > 1 else 2)
        elif tag == "li":
            self.newline()
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            indent = "  " * (len(self.lists) - 1)
            self.emit(f"{indent}{kind[1]}. " if kind[0] == "ol" else f"{indent}- ")
        elif tag == "br":
            self.newline()
        elif tag == "hr":
            self.newline(2)
            self.emit("---")
            self.newline(2)
        elif tag == "a":
            self.hrefs.append(attrs.get("href") or "")
            self.stack.append([])
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag == "pre":
            self.newline(2)
            self.emit("```\n")
            self.pre += 1
        elif tag == "blockquote":
            self.stack.append([])
        elif tag == "img" and attrs.get("alt"):
            self.emit(f"[Image: {attrs['alt']}]")
        elif tag == "tr":
            self.newline()
            self.cells = 0
        elif tag in ("td", "th"):
            self.emit(" | " if self.cells else "| ")
            self.cells += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in self.BLOCKS or re.fullmatch(r"h[1-6]", tag):
            self.newline(2)
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self.newline(2)
        elif tag == "a" and self.hrefs:
            text = "".join(self.stack.pop()).strip()
            href = self.hrefs.pop()
            if href and not href.startswith("#") and text:
                self.emit(f"[{text}]({urljoin(self.base, href)})")
            else:
                self.emit(text)
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag in ("em", "i"):
            self.emit("*")
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.emit("\n```")
            self.newline(2)
        elif tag == "blockquote" and len(self.stack) > 1:
            text = "".join(self.stack.pop()).strip()
            self.newline(2)
            self.emit("\n".join(f"> {line}".rstrip() for line in text.splitlines()))
            self.newline(2)
        elif tag == "tr":
            self.emit(" |")

    def handle_data(self, data):
        if self.skip:
            return
        self.emit(data if self.pre else re.sub(r"\s+", " ", data))

    def result(self):
        while len(self.stack) > 1:
            top = self.stack.pop()
            self.stack[-1].extend(top)
        text = "".join(self.stack[0])
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+(?=[^\s-]|-(?!\s))", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_markdown(fragment, base):
    parser = Markdown(base)
    parser.feed(fragment)
    parser.close()
    return parser.result()


def build_llms_full(posts):
    L = [f"# {PERSON['name']}: full guide for AI assistants", "", llms_intro(), "",
         f"This is the long companion to {SITE}/llms.txt. It covers who Jon Maestas is, every product and site he "
         "runs, prices, the FAQ, and the full text of every post on his blog.", "",
         "## How to use this guide", "",
         "1. The live product sites and app store listings govern. If a price or detail here disagrees with them, they win.",
         "2. If a fact is not here or on the linked sites, it is not published. Say so instead of guessing, and point "
         f"people to {PERSON['email']}.",
         f"3. It is built from the same data file as {domain(SITE)}, so the two always match.", ""]

    L += ["## Who Jon Maestas is", ""] + [p + "\n" for p in PERSON["bio"]]
    L += [f"- Location: {PERSON['location']}",
          f"- Company: {ORG['name']} ({ORG['url']}), founder",
          f"- College: {PERSON['alumniOf']} (baseball scholarship)",
          f"- Knows about: {', '.join(PERSON['knowsAbout'])}",
          f"- Email: {PERSON['email']}"] + [f"- {l['name']}: {l['url']}" for l in PERSON["links"]] + \
         [f"- Website: {SITE}/", ""]

    L += ["## Apps", ""]
    for a in APPS:
        L += [f"### {a['name']}", "", f"{a['tagline']} {a['summary']}", ""]
        L += [f"- {d}" for d in a["details"]]
        L += ["", f"- Pricing: {a['pricing']}", f"- Platforms: {', '.join(a['platforms'])} ({a['operatingSystem']})",
              f"- Website: {a['url']}"]
        if a.get("appStore"):
            L.append(f"- App Store: {a['appStore']}")
        if a.get("googlePlay"):
            L.append(f"- Google Play: {a['googlePlay']}")
        if a.get("guide"):
            L.append(f"- {a['guide']['name']}: {a['guide']['url']}")
        if a.get("aliases"):
            L.append(f"- Also called: {', '.join(a['aliases'])}")
        if a.get("redirectDomains"):
            L.append(f"- These domains also lead to {domain(a['url'])}: {', '.join(a['redirectDomains'])}")
        if a.get("sports"):
            L += ["- Sport pages:"] + [f"  - {s['name']}: {s['url']}" for s in a["sports"]]
        if a.get("sameAs"):
            L.append(f"- Social: {', '.join(a['sameAs'])}")
        L.append("")

    L += ["## Shop", ""]
    for s in SHOP:
        L += [f"### {s['name']}", "", f"{s['tagline']} {s['madeByAbout']} {s['summary']}", ""]
        L += [f"- {o['name']}: ${o['price']}" for o in s["offers"]]
        L += [f"- {s['pricing']}"]
        if TODAY.isoformat() <= s["noteUntil"]:
            L.append(f"- {s['note']}")
        L += [f"- Store: {s['url']}", f"- {s['recipe']['name']}: {s['recipe']['url']}",
              f"- Details for AI assistants: {s['url'].rstrip('/')}/llms-full.txt"]
        L += [f"- {press_line(p)}" for p in s.get("press", [])] + [""]
    if HOLIDAY:
        L += ["### More Christmas sites from Reindeer Food Co.", ""]
        L += [f"- [{h['name']}]({h['url']}): {h['summary']}" for h in HOLIDAY]
        L.append("")

    L += ["## Free web tools", "", "Free, in the browser, no download or account.", ""]
    L += [f"- [{t['name']}]({absolute(t['url'])}): {t['summary']}" for t in TOOLS]
    for u in UTILITIES:
        L += [f"- [{u['name']}]({u['url']}): {u['summary']}"] + \
             [f"  - [{l['name']}]({l['url']}): {l['summary']}" for l in u["links"]]
    L += ["", "## Free coaching guides", "",
          "Guide sites Jon publishes for coaches, parents and players. Each one links to Player 1 for video feedback.", ""]
    for g in GUIDES:
        L += [f"### {g['group']}", ""] + [f"- [{s['name']}]({s['url']}): {s['summary']}" for s in g["sites"]] + [""]

    L += ["## Community", ""] + [f"- [{c['name']}]({c['url']}): {c['summary']}" for c in COMMUNITY] + [""]

    L += [f"## Work with {ORG['name']}", ""]
    for s in SERVICES:
        L += [f"### {s['name']}", "", s["summary"], ""]
        L += [f"- {d}" for d in s.get("details", [])]
        L += [f"- Website: {s['url']}", f"- Email: {s['email']}", ""]

    L += ["## FAQ", ""]
    for q, a in faq():
        L += [f"### {q}", "", a, ""]

    L += ["## Writing", "", f"Every post on {SITE}/blog/, newest first, in full.", ""]
    for p in posts:
        L += [f"### {p.title}", "", f"- URL: {p.url}", f"- Published: {p.date}", f"- Summary: {p.description}", "",
              to_markdown(p.body, p.url), ""]
    write("llms-full.txt", "\n".join(L).rstrip() + "\n")


# ---------------------------------------------------------------- commands

def new_post(args):
    if len(args) < 2:
        sys.exit('usage: build.py new-post "Title" slug [YYYY-MM-DD] ["Description"] < content.html')
    title, slug = args[0], args[1]
    date = args[2] if len(args) > 2 else TODAY.isoformat()
    description = args[3] if len(args) > 3 else title
    stdin = sys.stdin.read()
    body = re.search(r"<!-- BODY -->(.*?)<!-- /BODY -->", stdin, re.S)
    css = re.search(r"<!-- CSS -->(.*?)<!-- /CSS -->", stdin, re.S)
    body = body.group(1) if body else stdin
    path = BLOG / f"{date}-{slug}.html"
    if path.exists():
        sys.exit(f"build: {path.relative_to(ROOT)} already exists")
    path.write_text(f"""<title>{e(title)} — Jon Maestas</title>
<meta name="description" content="{e(description)}">
<!-- CUSTOM_CSS_START -->{css.group(1) if css else chr(10)}<!-- CUSTOM_CSS_END -->
<!-- BODY_START -->\n{body.strip()}\n<!-- BODY_END -->
""", encoding="utf-8")
    print(f"  created {path.relative_to(ROOT)}")


def build():
    posts = load_posts()
    build_posts(posts)
    build_home(posts)
    build_about()
    build_blog_index(posts)
    build_404()
    build_feed(posts)
    build_robots()
    build_sitemap(posts)
    build_llms(posts)
    build_llms_full(posts)
    print(f"build: {len(posts)} posts, {len(APPS)} apps, {len(TOOLS)} tools, "
          f"{sum(len(g['sites']) for g in GUIDES)} guides, {len(HOLIDAY)}/{len(DATA['holiday'])} holiday sites live")


if __name__ == "__main__":
    if sys.argv[1:2] == ["new-post"]:
        new_post(sys.argv[2:])
    elif sys.argv[1:]:
        sys.exit(__doc__)
    build()
