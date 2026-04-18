"""
site_builder.py

Converts markdown articles into a full static HTML site.
Outputs to advert/finance/site/dist/ ready for Cloudflare Pages.

Usage:
    python shared/execution/site_builder.py
"""

import math
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import markdown

ADVERT_ROOT  = Path(__file__).parent.parent.parent
PROJECT_ROOT = ADVERT_ROOT.parent
TMP_DIR      = PROJECT_ROOT / ".tmp"

ARTICLES_DIR  = TMP_DIR / "articles" / "finance"
SITE_DIR      = ADVERT_ROOT / "finance" / "site"
TEMPLATES_DIR = SITE_DIR / "templates"
STATIC_DIR    = SITE_DIR / "static"
DIST_DIR      = SITE_DIR / "dist"

CATEGORIES = {
    "credit": "Credit Cards",
    "invest": "Investing",
    "budget": "Budgeting",
    "side hustle": "Side Hustles",
    "saving": "Budgeting",
    "debt": "Debt Payoff",
    "passive income": "Side Hustles",
    "make money": "Side Hustles",
    "income": "Side Hustles",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def render_base(title: str, description: str, canonical: str, content: str) -> str:
    base = read_template("base.html")
    return (base
        .replace("{{ title }}", title)
        .replace("{{ description }}", description)
        .replace("{{ canonical }}", canonical)
        .replace("{{ content }}", content))


def parse_frontmatter(text: str) -> tuple[dict, str]:
    meta = {}
    if text.startswith("---"):
        end = text.index("---", 3)
        for line in text[3:end].strip().splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        text = text[end+3:].strip()
    return meta, text


def guess_category(keyword: str, content: str) -> str:
    combined = (keyword + " " + content[:200]).lower()
    for trigger, cat in CATEGORIES.items():
        if trigger in combined:
            return cat
    return "Personal Finance"


def read_time(text: str) -> int:
    return max(1, math.ceil(len(text.split()) / 200))


def slug_from_path(path: Path) -> str:
    return path.stem


def excerpt(content: str, length: int = 160) -> str:
    clean = re.sub(r"#+ ", "", content)
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
    clean = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", clean)
    clean = " ".join(clean.split())
    return clean[:length].rsplit(" ", 1)[0] + "..."


# ---------------------------------------------------------------------------
# Article card HTML
# ---------------------------------------------------------------------------

CATEGORY_EMOJI = {
    "Credit Cards":    "💳",
    "Investing":       "📈",
    "Budgeting":       "💰",
    "Side Hustles":    "🚀",
    "Debt Payoff":     "🏦",
    "Personal Finance": "📊",
}


def make_card(article: dict, featured: bool = False) -> str:
    emoji = CATEGORY_EMOJI.get(article['category'], "📄")
    if featured:
        return f"""
    <div class="card card-featured">
      <div class="card-featured-img">{emoji}</div>
      <div class="card-body">
        <span class="card-tag">{article['category']}</span>
        <h3 class="card-title"><a href="/{article['slug']}/">{article['title']}</a></h3>
        <p class="card-excerpt">{article['excerpt']}</p>
        <div class="card-footer">
          <span>{article['date']} &bull; {article['read_time']} min read</span>
          <a href="/{article['slug']}/" class="card-read-more">Read more &rarr;</a>
        </div>
      </div>
    </div>"""
    return f"""
    <div class="card">
      <div class="card-body">
        <span class="card-tag">{article['category']}</span>
        <h3 class="card-title"><a href="/{article['slug']}/">{article['title']}</a></h3>
        <p class="card-excerpt">{article['excerpt']}</p>
        <div class="card-footer">
          <span>{article['date']} &bull; {article['read_time']} min read</span>
          <a href="/{article['slug']}/" class="card-read-more">Read more &rarr;</a>
        </div>
      </div>
    </div>"""


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build():
    print("Building site...")

    # Clean dist but preserve .git so pushes keep working
    if DIST_DIR.exists():
        for item in DIST_DIR.iterdir():
            if item.name == ".git":
                continue
            if item.is_dir():
                def remove_readonly(func, path, _):
                    import stat
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                shutil.rmtree(item, onerror=remove_readonly)
            else:
                item.unlink()
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # Copy static files
    shutil.copytree(STATIC_DIR, DIST_DIR / "static")

    # Copy verification files from static to root
    for verify_file in STATIC_DIR.glob("*-verify.html"):
        shutil.copy(verify_file, DIST_DIR / verify_file.name)
    print(f"  Copied static files")

    # Load all articles
    md_files = sorted(ARTICLES_DIR.glob("*.md"), reverse=True) if ARTICLES_DIR.exists() else []
    print(f"  Found {len(md_files)} articles")

    articles = []
    for path in md_files:
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)

        # Extract title from H1
        title = meta.get("title", path.stem.replace("-", " ").title())
        lines = body.splitlines()
        for line in lines:
            if line.startswith("# "):
                raw_title = line[2:].strip()
                # Strip markdown links from title e.g. [Foo](/bar/) -> Foo
                title = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', raw_title)
                break

        # Remove H1 and inline "Meta Description:" lines from body
        clean_lines = []
        skip_next = False
        for line in lines:
            if skip_next and line.startswith("[") and line.endswith("]"):
                skip_next = False
                continue
            if line.startswith("# "):
                skip_next = True
                continue
            # Strip standalone Meta Description lines injected by article writer
            if re.match(r'^\*?\*?Meta Description:?\*?\*?', line.strip(), re.IGNORECASE):
                continue
            clean_lines.append(line)
        body_clean = "\n".join(clean_lines).strip()

        slug = slug_from_path(path)
        keyword = meta.get("keyword", slug.replace("-", " "))
        category = guess_category(keyword, body_clean)
        rt = read_time(body_clean)
        ex = excerpt(body_clean)
        date = meta.get("generated", "2026-04-04")[:10]
        date_fmt = datetime.strptime(date, "%Y-%m-%d").strftime("%b %d, %Y") if date else "April 2026"

        articles.append({
            "title":    title,
            "slug":     slug,
            "keyword":  keyword,
            "category": category,
            "excerpt":  ex,
            "date":     date_fmt,
            "read_time": rt,
            "body_md":  body_clean,
            "meta_desc": meta.get("meta", ex),
        })

    # Sort newest first by generated date
    articles.sort(key=lambda a: a["date"], reverse=True)

    # Build article pages
    article_tmpl = read_template("article.html")
    md_converter = markdown.Markdown(extensions=["tables", "fenced_code"])

    for art in articles:
        md_converter.reset()
        body_html = md_converter.convert(art["body_md"])

        cat_slug = art["category"].lower().replace(" ", "-").replace("/", "-")
        article_html = (article_tmpl
            .replace("{{ category }}", art["category"])
            .replace("{{ category_slug }}", cat_slug)
            .replace("{{ title }}", art["title"])
            .replace("{{ date }}", art["date"])
            .replace("{{ read_time }}", str(art["read_time"]))
            .replace("{{ body }}", body_html))

        page = render_base(
            title=art["title"],
            description=art["meta_desc"],
            canonical=f"/{art['slug']}/",
            content=article_html,
        )

        out_dir = DIST_DIR / art["slug"]
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(page, encoding="utf-8")

    print(f"  Built {len(articles)} article pages")

    # Build homepage
    home_tmpl = read_template("home.html")
    cards = []
    for i, a in enumerate(articles[:12]):
        cards.append(make_card(a, featured=(i == 0)))
    cards_html = "\n".join(cards)
    home_content = home_tmpl.replace("{{ article_cards }}", cards_html)

    home_page = render_base(
        title="Personal Finance Tips for Young Adults",
        description="Practical money advice from Jordan Hale. Credit cards, investing, budgeting and side hustles explained simply.",
        canonical="/",
        content=home_content,
    )
    (DIST_DIR / "index.html").write_text(home_page, encoding="utf-8")
    print(f"  Built homepage with {min(12, len(articles))} article cards")

    # Build category pages
    category_map = {
        "credit-cards":  "Credit Cards",
        "investing":     "Investing",
        "budgeting":     "Budgeting",
        "side-hustles":  "Side Hustles",
        "debt-payoff":   "Debt Payoff",
    }
    cat_count = 0
    for slug, label in category_map.items():
        cat_articles = [a for a in articles if a["category"] == label]
        if not cat_articles:
            # Show all articles if none match yet
            cat_articles = articles

        cards = [make_card(a, featured=(i == 0)) for i, a in enumerate(cat_articles[:12])]
        cat_content = f"""
<div class="container">
  <section class="section">
    <div class="section-header">
      <div class="section-label">{label}</div>
      <h1 class="section-title">{label} Guides</h1>
      <p class="section-sub">Practical, research-backed advice from Jordan Hale.</p>
    </div>
    <div class="pills">
      <a href="/" class="pill">All</a>
      <a href="/credit-cards/" class="pill{'  active' if slug == 'credit-cards' else ''}">Credit Cards</a>
      <a href="/investing/" class="pill{'  active' if slug == 'investing' else ''}">Investing</a>
      <a href="/budgeting/" class="pill{'  active' if slug == 'budgeting' else ''}">Budgeting</a>
      <a href="/side-hustles/" class="pill{'  active' if slug == 'side-hustles' else ''}">Side Hustles</a>
      <a href="/debt-payoff/" class="pill{'  active' if slug == 'debt-payoff' else ''}">Debt Payoff</a>
    </div>
    <div class="card-grid">
      {"".join(cards)}
    </div>
  </section>
</div>"""

        cat_page = render_base(
            title=f"{label} - The Finance Blueprint",
            description=f"In-depth {label.lower()} guides from Jordan Hale. Practical advice with no fluff.",
            canonical=f"/{slug}/",
            content=cat_content,
        )
        cat_dir = DIST_DIR / slug
        cat_dir.mkdir(parents=True, exist_ok=True)
        (cat_dir / "index.html").write_text(cat_page, encoding="utf-8")
        cat_count += 1

    print(f"  Built {cat_count} category pages")

    # Build about page
    about_content = """
<div class="article-header-section">
  <div class="article-header-inner">
    <div class="article-breadcrumb">
      <a href="/">Home</a>
      <span>&rsaquo;</span>
      <span>About Jordan</span>
    </div>
    <h1 class="article-title">About Jordan Hale</h1>
  </div>
</div>

<div class="article-layout">
  <main>
    <div class="article-content">
      <div style="display:flex; align-items:center; gap:24px; margin-bottom:36px; padding:28px; background:var(--bg-alt); border-radius:12px; border:1px solid var(--border);">
        <div style="width:100px; height:100px; border-radius:50%; background:var(--green); display:flex; align-items:center; justify-content:center; color:#fff; font-family:var(--font-heading); font-size:40px; font-weight:800; flex-shrink:0;">JH</div>
        <div>
          <h2 style="margin-bottom:4px; border:none; padding:0; font-size:22px;">Jordan Hale</h2>
          <p style="color:var(--text-muted); font-size:15px; margin:0;">Personal Finance Writer &bull; The Finance Blueprint</p>
        </div>
      </div>

      <h2>My Story</h2>
      <p>I graduated college with $28,000 in student loan debt, a $35,000 salary, and absolutely no idea what I was doing with money. Nobody taught me how credit scores worked, what a Roth IRA was, or why I should care about compound interest.</p>
      <p>So I figured it out the hard way. I read everything I could find, made plenty of mistakes, and eventually paid off all $28,000 in three years while building a solid investment portfolio from scratch.</p>
      <p>Now I write The Finance Blueprint to give you the shortcut I never had. Everything here is based on what actually worked for me and thousands of people in similar situations.</p>

      <h2>What This Site Is About</h2>
      <p>The Finance Blueprint covers four things that have the biggest impact on your financial life:</p>
      <ul>
        <li><strong>Credit Cards</strong> - how to build credit, which cards are worth it, and how to avoid the traps</li>
        <li><strong>Investing</strong> - where to start, what to invest in, and how to stay consistent</li>
        <li><strong>Budgeting</strong> - systems that actually work without making you miserable</li>
        <li><strong>Side Hustles</strong> - realistic ways to earn more and build income beyond your 9-5</li>
      </ul>

      <h2>My Approach</h2>
      <p>I don't do sponsored content or paid placements. When I recommend a product, it's because I've researched it or used it myself. Some links on this site are affiliate links, which means I earn a small commission if you sign up - but this never influences what I recommend.</p>
      <p>I also don't believe in complex strategies or get-rich-quick schemes. The path to financial security is boring: spend less than you earn, invest the difference, and stay consistent for a long time. I just try to make that path as clear and actionable as possible.</p>

      <h2>Get in Touch</h2>
      <p>Have a question or topic you'd like me to cover? Email me at <a href="mailto:hello@thefinanceblueprint.com">hello@thefinanceblueprint.com</a> - I read every message, even if I can't always reply to each one.</p>
    </div>
  </main>

  <aside class="sidebar">
    <div class="sidebar-sticky">
      <div class="sidebar-cta">
        <h3>Free Money Checklist</h3>
        <p>The 10-step plan Jordan used to pay off $28K in debt.</p>
        <a href="/" class="btn btn-sm" style="width:100%; justify-content:center;">Get It Free</a>
      </div>
      <div class="sidebar-widget">
        <div class="sidebar-widget-title">Top Guides</div>
        <ul class="sidebar-links">
          <li><a href="/best-credit-cards-for-beginners/">&#128179; Best Starter Credit Cards</a></li>
          <li><a href="/how-to-build-credit-from-scratch/">&#128200; Build Credit from Zero</a></li>
          <li><a href="/how-to-start-investing-with-100-dollars/">&#128176; Invest Your First $100</a></li>
          <li><a href="/best-budgeting-apps-2026/">&#128202; Best Budgeting Apps 2026</a></li>
        </ul>
      </div>
    </div>
  </aside>
</div>"""

    about_page = render_base(
        title="About Jordan Hale - The Finance Blueprint",
        description="Jordan Hale paid off $28K in debt in 3 years. Now he writes The Finance Blueprint to help young adults take control of their money.",
        canonical="/about/",
        content=about_content,
    )
    about_dir = DIST_DIR / "about"
    about_dir.mkdir(parents=True, exist_ok=True)
    (about_dir / "index.html").write_text(about_page, encoding="utf-8")
    print(f"  Built about page")

    print(f"\nDone. Site built to: {DIST_DIR}")
    print(f"Total pages: {len(articles) + 2 + cat_count}")

    # Build sitemap.xml
    base_url = "https://www.thefinanceblueprint.com"
    today = datetime.now().strftime("%Y-%m-%d")
    urls = []

    # Homepage
    urls.append(f"""  <url>
    <loc>{base_url}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>""")

    # Category pages
    for slug in category_map:
        urls.append(f"""  <url>
    <loc>{base_url}/{slug}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>""")

    # About page
    urls.append(f"""  <url>
    <loc>{base_url}/about/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>""")

    # Article pages
    for art in articles:
        urls.append(f"""  <url>
    <loc>{base_url}/{art['slug']}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>""")

    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    sitemap += "\n".join(urls)
    sitemap += "\n</urlset>"
    (DIST_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    print(f"  Built sitemap.xml with {len(urls)} URLs")

    # Build robots.txt
    robots = f"""User-agent: *
Allow: /

Sitemap: {base_url}/sitemap.xml
"""
    (DIST_DIR / "robots.txt").write_text(robots, encoding="utf-8")
    print(f"  Built robots.txt")

    # Build ads.txt (required for AdSense)
    ads_txt = "google.com, pub-5307963212708530, DIRECT, f08c47fec0942fa0\n"
    (DIST_DIR / "ads.txt").write_text(ads_txt, encoding="utf-8")
    print(f"  Built ads.txt")


if __name__ == "__main__":
    build()
