#!/usr/bin/env python3
"""Render writing/posts/*.md into writing/<slug>.html, writing.html, feed.xml, and refresh sitemap.xml.

Front matter (strings only):
  title, date (YYYY-MM-DD), summary, optional external (URL: links out, no page rendered),
  optional outlet (shown with external), optional draft: true (excluded everywhere).
Needs pandoc. With no published posts it writes nothing and removes stale outputs, so the
Writing page never exists empty. Idempotent: reruns change nothing.
"""
import datetime as dt, email.utils, html, pathlib, re, shutil, subprocess, sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent
POSTS, OUT = ROOT / "writing/posts", ROOT / "writing"
SITE = "https://garrettthrash.com"
INDEX, FEED, SITEMAP = ROOT / "writing.html", ROOT / "feed.xml", ROOT / "sitemap.xml"
BEGIN, END = "<!-- BEGIN AUTO-WRITING -->", "<!-- END AUTO-WRITING -->"

def write_if_changed(path, text):
    if path.exists() and path.read_text() == text: return False
    path.write_text(text); print("updated", path.relative_to(ROOT)); return True

def meta(md):
    out = subprocess.run(["pandoc", str(md), "-t", "plain", "-s", "--template", str(OUT / "meta.template.txt")],
                         capture_output=True, text=True, check=True).stdout.rstrip("\n")
    title, date, summary, external, outlet, draft = (out.split("\t") + [""] * 6)[:6]
    if not title or not date or not summary: sys.exit(f"{md.name}: title, date and summary are required")
    try: d = dt.date.fromisoformat(date.strip())
    except ValueError: sys.exit(f"{md.name}: date must be YYYY-MM-DD, got {date!r}")
    return dict(slug=md.stem, title=title, date=d, summary=summary, external=external.strip(),
                outlet=outlet.strip(), draft=draft.strip().lower() == "true")

def render(md, m):
    pretty = m["date"].strftime("%B %-d, %Y")
    body = subprocess.run(["pandoc", str(md), "-f", "markdown", "-t", "html5", "-s", "--wrap=none", "--mathml",
                           "--template", str(OUT / "post.template.html"), "-M", f"slug={m['slug']}", "-M", f"datepretty={pretty}"],
                          capture_output=True, text=True, check=True).stdout
    if re.search(r"<article>.*<h1", body, re.S): print(f"warning: {md.name} uses a top-level # heading; use ## inside posts")
    return body

def main():
    if not shutil.which("pandoc"): sys.exit("pandoc is not installed; cannot build writing/")
    posts = [meta(p) | {"path": p} for p in sorted(POSTS.glob("*.md"))]
    live = sorted((p for p in posts if not p["draft"]), key=lambda p: (p["date"], p["slug"]), reverse=True)
    keep = set()
    for p in live:
        if p["external"]: continue
        out = OUT / f"{p['slug']}.html"; keep.add(out)
        write_if_changed(out, render(p["path"], p))
    for stale in OUT.glob("*.html"):
        if not stale.name.endswith(".template.html") and stale not in keep: stale.unlink(); print("removed", stale.relative_to(ROOT))
    if not live:
        for f in (INDEX, FEED):
            if f.exists(): f.unlink(); print("removed", f.name)
        print("no published posts; writing page not generated"); refresh_sitemap(); return
    # index block
    items = []
    for p in live:
        href = p["external"] or f"writing/{p['slug']}.html"
        where = f' <span class="muted">· {html.escape(p["outlet"])}</span>' if p["outlet"] else ""
        ext = ' target="_blank" rel="noopener"' if p["external"] else ""
        items.append(f'    <li><span class="when">{p["date"].isoformat()}</span><div><a href="{html.escape(href)}"{ext}>{html.escape(p["title"])}</a>{where}<p class="muted">{html.escape(p["summary"])}</p></div></li>')
    block = BEGIN + "\n  <ul class=\"posts\">\n" + "\n".join(items) + "\n  </ul>\n  " + END
    if INDEX.exists() and BEGIN in INDEX.read_text():
        page = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: block, INDEX.read_text(), count=1, flags=re.S)
    else:
        page = (ROOT / "writing/index.template.html").read_text().replace("<!-- AUTO -->", block)
    write_if_changed(INDEX, page)
    # feed
    rss = ET.Element("rss", version="2.0", attrib={"xmlns:atom": "http://www.w3.org/2005/Atom"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "Garrett Thrash: Writing"
    ET.SubElement(ch, "link").text = f"{SITE}/writing.html"
    ET.SubElement(ch, "description").text = "Notes from a neuroengineering PhD, medical training, and working with AI."
    ET.SubElement(ch, "{http://www.w3.org/2005/Atom}link", href=f"{SITE}/feed.xml", rel="self", type="application/rss+xml")
    for p in live:
        it = ET.SubElement(ch, "item"); url = p["external"] or f"{SITE}/writing/{p['slug']}.html"
        ET.SubElement(it, "title").text = p["title"]; ET.SubElement(it, "link").text = url
        ET.SubElement(it, "guid", isPermaLink="true").text = url
        ET.SubElement(it, "description").text = p["summary"]
        ET.SubElement(it, "pubDate").text = email.utils.format_datetime(dt.datetime(p["date"].year, p["date"].month, p["date"].day, 12, tzinfo=dt.timezone.utc))
    ET.indent(rss); write_if_changed(FEED, '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode") + "\n")
    refresh_sitemap()

def refresh_sitemap():
    pages = ["index.html"] + sorted(p.name for p in ROOT.glob("*.html") if p.name not in ("index.html", "404.html"))
    pages += sorted(f"writing/{p.name}" for p in OUT.glob("*.html") if not p.name.endswith(".template.html"))
    urls = "".join(f"  <url><loc>{SITE}/{'' if p == 'index.html' else p}</loc></url>\n" for p in pages)
    write_if_changed(SITEMAP, '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n")

if __name__ == "__main__":
    main()
