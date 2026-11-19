#!/usr/bin/env python3
"""Check the built site before it is committed.

Every generated HTML page must have: links and #anchors that resolve (including absolute links
back to garrettthrash.com), the head tags that search and share previews need, exactly one h1,
no duplicate ids, and valid JSON-LD. Nothing on the site may contain a banned word, a British
spelling, an em dash, or a CHECK: comment left from staging a commonplace entry. sitemap.xml must
exist and parse; the feeds (feed.xml, commonplace/feed.xml) must parse when present. Commonplace
pages are checked like any other page; the preview in drafts/ is not checked.
This is a guard against common mistakes, not a full HTML validator.

Usage: python3 tools/check-site.py     Exit status 1 if anything is wrong.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "pages", "templates", "tools", "tests", "drafts", "node_modules"}
HEAD_TAGS = ['<title>', 'name="description"', 'og:title', 'og:image" content="https://',
             'rel="icon" href="/favicon.svg"', 'rel="canonical"']
BANNED = ["physician", "stealth", "pre-seed", "Tools I build", "hidden>", "direct AI", "AnalyzeLFPs", "analyzelfps",
          "—", "&mdash;", "CHECK:"]
BRITISH = re.compile(r"\b(organis\w*|modell\w*|labell\w*|colour\w*|behaviour\w*|centre\w*|favour\w*|analys(e|ed|ing)\b)",
                     re.I)
SITE = "https://garrettthrash.com"
EXTERNAL = ("http:", "https:", "mailto:", "tel:", "data:", "javascript:")
FEEDS = ("feed.xml", "commonplace/feed.xml")
LINK = re.compile(r"""(?:href|src)\s*=\s*(["'])(.*?)\1""")


def site_pages(root: Path = ROOT) -> list[Path]:
    """Built HTML pages, skipping sources, templates and tooling."""
    return sorted(p for p in root.rglob("*.html") if not SKIP_DIRS & set(p.relative_to(root).parts))


def resolve(page: Path, url: str, root: Path = ROOT) -> Path:
    """The file a site-local link points at ("/research/" -> research/index.html)."""
    path = unquote(htmllib.unescape(url).split("#")[0].split("?")[0])
    target = root / path.lstrip("/") if path.startswith("/") else (page.parent / path if path else page)
    return target / "index.html" if path.endswith("/") or target.is_dir() else target


def link_problems(page: Path, html: str, root: Path = ROOT) -> list[str]:
    """Broken local links and missing #anchors on one page."""
    problems = []
    for _, url in LINK.findall(html):
        if url.startswith(SITE):
            url = url[len(SITE):] or "/"
        elif url.startswith(EXTERNAL):
            continue
        target = resolve(page, url, root)
        if not target.exists():
            problems.append(f"broken link {url}")
        elif "#" in url and target.suffix == ".html":
            anchor = unquote(url.split("#", 1)[1])
            if anchor and f'id="{anchor}"' not in target.read_text(encoding="utf-8"):
                problems.append(f"missing anchor {url}")
    return problems


def head_problems(html: str) -> list[str]:
    """Missing head tags, wrong h1 count, unparsable JSON-LD."""
    problems = [f"missing {tag}" for tag in HEAD_TAGS if tag not in html]
    if (n := len(re.findall(r"<h1[\s>]", html))) != 1:
        problems.append(f"{n} h1 elements")
    ids = re.findall(r'\sid="([^"]+)"', html)
    problems += [f"duplicate id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            json.loads(block)
        except json.JSONDecodeError as err:
            problems.append(f"JSON-LD: {err}")
    return problems


def wording_problems(html: str) -> list[str]:
    """Banned words, em dashes and British spellings in the page text."""
    problems = [f"banned {word!r}" for word in BANNED if word in html]
    text = re.sub(r"<[^>]+>", " ", html)
    problems += [f"British spelling {m.group(0)!r}" for m in BRITISH.finditer(text)]
    return problems


def xml_problems(root: Path = ROOT) -> list[str]:
    """sitemap.xml must exist and parse; the feeds must parse when present."""
    problems = [] if (root / "sitemap.xml").exists() else ["sitemap.xml is missing"]
    for name in ("sitemap.xml", *FEEDS):
        if (root / name).exists():
            try:
                ET.parse(root / name)
            except ET.ParseError as err:
                problems.append(f"{name}: {err}")
    return problems


def main() -> int:
    """Check every page and report; 0 if clean, 1 otherwise."""
    bad = 0
    for page in site_pages():
        html = page.read_text(encoding="utf-8")
        problems = link_problems(page, html) + wording_problems(html)
        if 'http-equiv="refresh"' not in html and page.name != "404.html":
            problems += head_problems(html)
        for problem in problems:
            print(f"{page.relative_to(ROOT)}: {problem}")
        bad += len(problems)
    for problem in xml_problems():
        print(problem)
        bad += 1
    print("OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
