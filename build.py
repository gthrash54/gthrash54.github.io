#!/usr/bin/env python3
"""Build garrettthrash.com from Markdown sources with pandoc. Never runs git.

Sources and what they become:
    pages/home.md               -> index.html
    pages/404.md                -> 404.html
    pages/<name>.md             -> <name>/index.html
    pages/projects/<slug>.md    -> projects/<slug>/index.html
    writing/posts/<slug>.md     -> writing/index.html, always (each section says "Coming soon." while
                                   empty); writing/<slug>/index.html for each post hosted here, and
                                   feed.xml once anything is published (a post with `draft: true`
                                   is not)
    commonplace/index.md and    -> commonplace/index.html and commonplace/topics/<topic>/index.html,
    commonplace/entries/*.md       always; commonplace/<slug>/index.html, commonplace/paths/<slug>/
                                   index.html and commonplace/feed.xml once entries exist (see
                                   commonplace.py for the entry format)
Also generated: redirect pages for the old addresses, sitemap.xml, build-manifest.txt.
Writing and Commonplace are always in the navigation; their feed links appear in every page's head
only once they have items.

Page front matter: `title` and `description` (required), `nav` (the current nav item),
`heading: false` (the page writes its own h1), `jsonld: true` (home only),
`now: YYYY-MM` (the About page's Now section), `class: home` (a class on <body>, for styles
that belong to one page).

Post front matter: `title`, `date` (YYYY-MM-DD) and `summary` (required); `updated: YYYY-MM-DD`;
`draft: true`; for a piece published elsewhere, `external: <url>` and `outlet: <name>` (both or
neither) instead of a body.

Tokens a page body can use; they are replaced after pandoc renders the page:
    <!-- pubs:all -->               every peer-reviewed publication, newest first
    <!-- pubs:keys k1 k2 ... -->    the listed bib keys, newest first
    <!-- pubs:compact k1 k2 ... --> the listed bib keys as short stacked items: journal and year,
                                    the title linked to its DOI (or PubMed), the first author
    {{pub_count}}                   number of peer-reviewed publications
    {{now}}                         the `now:` month spelled out, e.g. "October 2026"
    <!-- writing:recent -->         a Writing section: its heading and the newest HOME_RECENT
    <!-- commonplace:recent -->     posts or entries, or "Coming soon." (Home uses both)

Publications come from the Better BibTeX export named in site.json (the same file the LaTeX CV
uses). The rules mirror the CV: "Correction to:" errata dropped, newest first, owner in bold.

Usage:
    python3 build.py              build the site in place (what gets committed), prune files the
                                  last build made that this one did not, update build-manifest.txt
    python3 build.py --preview    build everything, drafts included (writing drafts and
                                  drafts/commonplace/), into drafts/_site, which git ignores.
                                  Writing and Commonplace show whenever they have anything.
                                  Never writes into the repository root, never touches the
                                  manifest, never prunes. preview.sh serves it with tools/serve.py.
Needs Python 3.10+ and pandoc.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import math
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import commonplace as cp
from commonplace import COMING_SOON, long_date

ROOT = Path(__file__).resolve().parent
SITE = "https://garrettthrash.com"
NAME = "Garrett W. Thrash"
PAGES = ROOT / "pages"
POSTS = ROOT / "writing" / "posts"
TEMPLATES = ROOT / "templates"
CONFIG = ROOT / "site.json"
MANIFEST = ROOT / "build-manifest.txt"
BOOK = ROOT / "commonplace"
ENTRIES = BOOK / "entries"
DRAFTS = ROOT / "drafts"
DRAFT_ENTRIES = DRAFTS / "commonplace"
DRAFT_POSTS = DRAFTS / "writing"           # unpublished essays live here, outside git
PREVIEW_OUT = DRAFTS / "_site"

# Old addresses: (new page, {old #section: new address}). Sections not listed go to the new page.
REDIRECTS = {
    "research.html": ("/research/", {
        "about": "/about/", "walker": "/research/#adaptive-dbs", "figures": "/research/",
        "tools": "/research/#tools", "experience": "/about/#experience", "service": "/about/#service"}),
    "publications.html": ("/publications/", {"publications": "/publications/", "presentations": "/publications/#posters"}),
    "talks.html": ("/about/#talks", {
        "lectures": "/about/#invited-lectures", "talks": "/about/#oral-presentations",
        "teaching": "/about/#teaching", "speaker": "/about/#organizers"}),
}
OWNER = "Thrash"           # family name set in bold in author lists
MAX_AUTHORS = 15           # longer author lists become: first 3, the owner, et al.
LEAD_AUTHORS = 3
NOW_MAX_DAYS = 90          # warn when the About page's Now section is older than this
HOME_RECENT = 3            # newest posts and entries in Home's Writing and Commonplace sections
WORDS_PER_MINUTE = 230     # reading speed for a post's "N min read"

JSONLD = {
    "@context": "https://schema.org",
    "@type": "Person",
    "name": NAME,
    "url": SITE + "/",
    "image": SITE + "/headshot.jpg",
    "email": "mailto:gthrash@uab.edu",
    "jobTitle": "M.D. Candidate; Incoming Ph.D. Student, Neuroengineering",
    "affiliation": {"@type": "CollegeOrUniversity", "name": "University of Alabama at Birmingham"},
    "alumniOf": {"@type": "CollegeOrUniversity", "name": "Birmingham-Southern College"},
    "sameAs": [
        "https://github.com/gthrash54",
        "https://www.linkedin.com/in/garrett-thrash-311709430/",
        "https://orcid.org/0009-0008-1061-8679",
        "https://scholar.google.com/citations?user=FJ4ulF4AAAAJ",
        "https://pubmed.ncbi.nlm.nih.gov/?term=Thrash+GW%5BAuthor%5D&sort=pubdate",
    ],
}

Bib = dict[str, dict[str, str]]


class BuildError(Exception):
    """A problem in the sources that should stop the build with a clear message."""


@dataclass(frozen=True)
class Post:
    """One piece of writing from writing/posts/. `external` is set for a piece published elsewhere."""
    path: Path
    slug: str
    title: str
    summary: str
    date: dt.date
    external: str = ""
    outlet: str = ""
    updated: dt.date | None = None
    draft: bool = False

    @property
    def url(self) -> str:
        """Where the title links: the outlet for a piece published elsewhere, else its page here."""
        return self.external or f"/writing/{self.slug}/"


@dataclass(frozen=True)
class FeedItem:
    """One item in an RSS feed."""
    title: str
    url: str
    summary: str
    date: dt.date


# ---------- bib(la)tex parsing (pure) ----------------------------------------------------------

def _read_braced(text: str, i: int) -> tuple[str, int]:
    """Read a {braced} value starting at text[i] == "{"; return the inside and the index after it."""
    depth, j = 0, i
    while True:
        depth += (text[j] == "{") - (text[j] == "}")
        j += 1
        if depth == 0:
            return text[i + 1:j - 1], j


def _read_value(text: str, i: int) -> tuple[str, int]:
    """Read one field value ({braced}, "quoted" or bare) starting at index i."""
    if text[i] == "{":
        return _read_braced(text, i)
    if text[i] == '"':
        j = text.index('"', i + 1)
        return text[i + 1:j], j + 1
    j = re.compile(r"[,}]").search(text, i).start()
    return text[i:j].strip(), j


def parse_bib(text: str) -> list[dict[str, str]]:
    """Parse BibLaTeX as Better BibTeX writes it into entries: {"type", "key", lowercased fields}.

    Syntax Better BibTeX never writes (parenthesized entries, @string macros, # concatenation)
    raises BuildError instead of being misread.
    """
    if re.search(r"@\w+\s*\(", text):
        raise BuildError("bib: parenthesized entries like @article(...) are not supported")
    head, field = re.compile(r"@(\w+)\s*\{", re.S), re.compile(r"\s*(\w+)\s*=\s*", re.S)
    tail = re.compile(r"\s*(,)?\s*(\})?", re.S)
    entries, i = [], 0
    while (m := head.search(text, i)):
        kind = m.group(1).lower()
        if kind in ("comment", "preamble"):
            i = _read_braced(text, m.end() - 1)[1]
            continue
        if kind == "string":
            raise BuildError("bib: @string macros are not supported")
        key_end = text.index(",", m.end())
        entry = {"type": kind, "key": text[m.end():key_end].strip()}
        i = key_end + 1
        while (fm := field.match(text, i)):
            entry[fm.group(1).lower()], i = _read_value(text, fm.end())
            if text[i:].lstrip().startswith("#"):
                raise BuildError(f"bib {entry['key']}: '#' string concatenation is not supported")
            closing = tail.match(text, i)
            i = closing.end()
            if closing.group(2):
                break
        else:
            i = text.index("}", i) + 1
        entries.append(entry)
    return entries


TEX_ESCAPES = {r"\&": "&", r"\%": "%", r"\_": "_", r"\$": "$", r"\#": "#"}


def plain(s: str) -> str:
    """Decode the TeX escapes Better BibTeX writes, drop case-protecting braces, collapse whitespace.

    Any other TeX command raises BuildError, so it can't reach the page as raw markup.
    """
    for escape, char in TEX_ESCAPES.items():
        s = s.replace(escape, char)
    if (command := re.search(r"\\[A-Za-z]+|\\.", s)):
        raise BuildError(f"bib: unsupported TeX command {command.group(0)!r} in {s!r}")
    return re.sub(r"\s+", " ", re.sub(r"[{}]", "", s)).strip()


def split_authors(field: str) -> list[str]:
    """Split an author field on ' and ', ignoring any 'and' inside {braces}."""
    names, depth, start = [], 0, 0
    for idx, char in enumerate(field):
        depth += (char == "{") - (char == "}")
        if depth == 0 and field.startswith(" and ", idx):
            names.append(field[start:idx])
            start = idx + 5
    names.append(field[start:])
    return [n.strip() for n in names if n.strip()]


def is_owner(family: str) -> bool:
    """True when a family name is the site owner's."""
    return bool(family) and family.split()[-1] == OWNER


def select_publications(entries: list[dict[str, str]]) -> Bib:
    """Keep the owner's journal articles, drop errata, and order newest first (keyed by citekey).

    Only @article entries count as peer-reviewed; preprints (@online) and items misfiled into the
    Zotero collection are skipped.
    """
    keep = [e for e in entries
            if e["type"] == "article"
            and not re.match(r"^\s*\{?Correction\s+to:", e.get("title", ""), re.I)
            and any(is_owner(parse_name(n)[0]) for n in split_authors(e.get("author", "")))]
    keep.sort(key=pub_date, reverse=True)
    return {e["key"]: e for e in keep}


# ---------- formatting references (pure) -------------------------------------------------------

def initials(given: str) -> str:
    """'Garrett Wayne' -> 'GW'."""
    parts = [p for p in re.split(r"[\s\-]+", plain(given).replace(".", " ")) if p]
    return "".join(p[0].upper() for p in parts)


Name = tuple[str, str, str, str]   # (family, given, particle, suffix)


def _split_particle(tokens: list[str]) -> tuple[str, str]:
    """['do', 'Campo'] -> ('Campo', 'do'): leading lowercase words are a particle."""
    particle = []
    while len(tokens) > 1 and tokens[0].islower():   # von, de, do, dos
        particle.append(tokens.pop(0))
    return " ".join(tokens), " ".join(particle)


def parse_name(raw: str) -> Name:
    """Split one BibTeX author into (family, given, particle, suffix).

    Handles Better BibTeX's `family=..., given=..., prefix=...` form, "Last, First",
    "Last, Jr., First", "First von Last", and fully braced corporate names.
    """
    raw = raw.strip()
    if re.search(r"\b(family|given)=", raw):
        parts = dict(kv.split("=", 1) for kv in re.split(r",\s*", raw) if "=" in kv)
        parts = {k.strip(): plain(v) for k, v in parts.items()}
        return parts.get("family", ""), parts.get("given", ""), parts.get("prefix", ""), parts.get("suffix", "")
    if raw.startswith("{") and raw.endswith("}") and _read_braced(raw, 0)[1] == len(raw):
        return plain(raw), "", "", ""                      # {World Health Organization}
    pieces = [p.strip() for p in raw.split(",")]
    if len(pieces) >= 3:                                   # Last, Jr., First
        family, particle = _split_particle(plain(pieces[0]).split())
        return family, plain(", ".join(pieces[2:])), particle, plain(pieces[1])
    if len(pieces) == 2:                                   # Last, First
        family, particle = _split_particle(plain(pieces[0]).split())
        return family, plain(pieces[1]), particle, ""
    tokens = plain(raw).split()                            # First von Last
    cut = next((k for k in range(1, len(tokens) - 1) if tokens[k].islower()), len(tokens) - 1)
    family, particle = _split_particle(tokens[cut:])
    return family, " ".join(tokens[:cut]), particle, ""


def fmt_name(family: str, given: str, particle: str, suffix: str = "") -> str:
    """('Thrash', 'Garrett W.', '', '') -> '<strong>Thrash GW</strong>' (bold only for the owner)."""
    text = " ".join(filter(None, [particle, family, initials(given) if given else "", suffix]))
    text = html.escape(text)
    return f"<strong>{text}</strong>" if is_owner(family) else text


def fmt_authors(field: str) -> str:
    """Format an author field Vancouver-style, shortening lists longer than MAX_AUTHORS."""
    names = [parse_name(n) for n in split_authors(field)]
    if len(names) <= MAX_AUTHORS:
        out = ", ".join(fmt_name(*n) for n in names)
    else:
        parts, skipped = [], False
        for idx, n in enumerate(names):
            if idx < LEAD_AUTHORS or is_owner(n[0]):
                if skipped:
                    parts.append("…")
                    skipped = False
                parts.append(fmt_name(*n))
            else:
                skipped = True
        out = ", ".join(parts + (["et al."] if skipped else []))
    return out if out.endswith(".") else out + "."


def pub_date(entry: dict[str, str]) -> tuple[int, int, int]:
    """(year, month, day) from `date` or `year`; missing parts are 0."""
    parts = ((entry.get("date") or entry.get("year", "")).split("-") + ["0", "0"])[:3]
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


def fmt_source(entry: dict[str, str]) -> str:
    """'<em>Journal</em> 30(1):28', or '<em>Journal</em>, 1–19' when there is no volume yet."""
    out = f"<em>{html.escape(plain(entry.get('journaltitle') or entry.get('journal', '')))}</em>"
    pages = html.escape(plain(entry.get("pages", "")).replace("--", "–"))
    if entry.get("volume"):
        out += f" {html.escape(plain(entry['volume']))}"
        if entry.get("number"):
            out += f"({html.escape(plain(entry['number']))})"
        if pages:
            out += f":{pages}"
    elif pages:
        out += f", {pages}"
    return out


def doi_url(entry: dict[str, str]) -> str:
    """The paper's https://doi.org/ address, or "" when it has no DOI."""
    return f"https://doi.org/{plain(entry['doi'])}" if entry.get("doi") else ""


def pubmed_url(entry: dict[str, str]) -> str:
    """The paper's PubMed address, or "" when it has no PubMed ID.

    Better BibTeX writes the ID as `eprint` with `eprinttype = {pubmed}`; older exports use `pmid`.
    """
    pmid = plain(entry["eprint"]) if entry.get("eprinttype", "").lower() == "pubmed" and entry.get("eprint") \
        else plain(entry.get("pmid", ""))
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""


def fmt_ids(entry: dict[str, str]) -> str:
    """DOI and PubMed links, or an empty string."""
    links = [f'<a href="{html.escape(url)}">{label}</a>'
             for url, label in ((doi_url(entry), "doi"), (pubmed_url(entry), "pubmed")) if url]
    return f' <span class="ids">{"".join(links)}</span>' if links else ""


def fmt_pub(entry: dict[str, str]) -> str:
    """One reference as a CV-style entry: year on the left, citation on the right."""
    title = html.escape(plain(entry.get("title", "")))
    if title and title[-1] not in ".?!":
        title += "."
    return (f'<div class="entry ref"><p>{pub_date(entry)[0]}</p>'
            f'<p>{fmt_authors(entry.get("author", ""))} <span class="t">{title}</span> '
            f'{fmt_source(entry)}.{fmt_ids(entry)}</p></div>')


def short_authors(field: str) -> str:
    """The first author, then "et al." when there are more: '<strong>Thrash GW</strong>, et al.'."""
    names = split_authors(field)
    if not names:
        return ""
    first = fmt_name(*parse_name(names[0]))
    return f"{first}, et al." if len(names) > 1 else first


def fmt_compact(entry: dict[str, str]) -> str:
    """One paper as a stacked item: "<journal> • <year>", the linked title, then the short author line.

    The title links to the DOI, or to PubMed when there is no DOI, or nowhere when there is neither.
    A paper without a journal or a year stops the build, since its label line would be wrong.
    """
    journal, year = plain(entry.get("journaltitle") or entry.get("journal", "")), pub_date(entry)[0]
    if not (journal and year):
        raise BuildError(f"bib {entry['key']}: pubs:compact needs a journal and a year")
    return card(f"{journal} • {year}", plain(entry.get("title", "")), doi_url(entry) or pubmed_url(entry),
                short_authors(entry.get("author", "")))


# ---------- stacked items: Home's lists and the Writing page (pure) ---------------------------------

def card(label: str, title: str, href: str, detail: str = "") -> str:
    """One stacked item: a small-caps label line, the title (linked when there is an href), a detail line.

    `label`, `title` and `href` are plain text and are escaped here; `detail` is HTML.
    """
    heading = f'<a href="{html.escape(href)}">{html.escape(title)}</a>' if href else html.escape(title)
    detail_line = f"<p>{detail}</p>" if detail else ""
    return f'<div class="card"><p>{html.escape(label)}</p><p>{heading}</p>{detail_line}</div>'


def card_list(cards: list[str]) -> str:
    """Cards in one stacked list, or "Coming soon." when there are none."""
    return '<div class="cards">\n' + "\n".join(cards) + "\n</div>" if cards else COMING_SOON


def post_card(p: Post) -> str:
    """A post as a stacked item: its date, its title and its summary (after the outlet, if elsewhere)."""
    detail = html.escape(p.summary)
    if p.outlet:
        detail = f"<em>{html.escape(p.outlet)}</em> • {detail}"
    return card(long_date(p.date), p.title, p.url, detail)


def entry_card(e: cp.Entry) -> str:
    """A commonplace entry as a stacked item: its type and month, its title and its summary."""
    return card(f"{cp.type_label(e.types)} • {cp.short_date(e.added)}", e.title, e.url, html.escape(e.summary))


def recent_section(heading: str, anchor: str, cards: list[str], more_href: str, more_label: str) -> str:
    """A Home section: its h2, then the cards and a link to the rest, or "Coming soon." when empty."""
    parts = [f'<h2 id="{anchor}">{heading}</h2>', card_list(cards)]
    if cards:
        parts.append(f'<p><a href="{more_href}">{more_label}</a></p>')
    return "\n".join(parts)


def writing_recent(posts: list[Post]) -> str:
    """Home's Writing section: the newest posts, here or elsewhere. `posts` is newest first."""
    return recent_section("Writing", "writing", [post_card(p) for p in posts[:HOME_RECENT]],
                          "/writing/", "All writing")


def commonplace_recent(entries: tuple[cp.Entry, ...]) -> str:
    """Home's Commonplace section: the newest entries."""
    return recent_section("Commonplace", "commonplace",
                          [entry_card(e) for e in cp.newest_first(entries)[:HOME_RECENT]],
                          "/commonplace/", "All entries")


# ---------- page assembly (pure) ---------------------------------------------------------------

def expand_tokens(body: str, pubs: Bib, ctx: dict[str, str], where: str,
                  sections: dict[str, str] | None = None) -> str:
    """Replace publication, section and {{name}} tokens in rendered HTML; fail on unknown keys or leftovers.

    `sections` holds what <!-- writing:recent --> and <!-- commonplace:recent --> become, keyed
    "writing" and "commonplace". Only pages under pages/ get them; a token without one fails.
    """
    sections = sections or {}

    def wanted(m: re.Match) -> list[dict[str, str]]:
        keys = m.group(1).split()
        if not keys:
            raise BuildError(f"{where}: {m.group(0)} lists no bib keys")
        if (missing := [k for k in keys if k not in pubs]):
            raise BuildError(f"{where}: unknown bib key(s): {', '.join(missing)}")
        return sorted((pubs[k] for k in keys), key=pub_date, reverse=True)

    def section(m: re.Match) -> str:
        if m.group(1) not in sections:
            raise BuildError(f"{where}: {m.group(0).strip()} only works on pages under pages/")
        return "\n" + sections[m.group(1)]

    body = substitute(body, ctx, where)
    body = re.sub(r"<!--\s*pubs:keys\s+(.*?)\s*-->", lambda m: "\n".join(fmt_pub(e) for e in wanted(m)), body)
    body = re.sub(r"<!--\s*pubs:compact\s+(.*?)\s*-->", lambda m: card_list([fmt_compact(e) for e in wanted(m)]),
                  body)
    body = re.sub(r"<!--\s*pubs:all\s*-->", lambda _: "\n".join(fmt_pub(e) for e in pubs.values()), body)
    body = re.sub(r"\n?<!--\s*(writing|commonplace):recent\s*-->", section, body)
    if (left := re.search(r"<!--\s*(pubs|writing|commonplace):", body)):
        raise BuildError(f"{where}: malformed token {left.group(0)}")
    return body


def substitute(text: str, values: dict[str, str], where: str) -> str:
    """Replace every {{name}} in one pass, so inserted values are never re-read as tokens.

    An unknown name raises BuildError.
    """
    def value(m: re.Match) -> str:
        if m.group(1) not in values:
            raise BuildError(f"{where}: no value for {m.group(0)}")
        return values[m.group(1)]
    return re.sub(r"\{\{(\w+)\}\}", value, text)


NAV = [("Research", "/research/", "research"), ("Commonplace", "/commonplace/", "commonplace"),
       ("Writing", "/writing/", "writing"), ("About &amp; CV", "/about/", "about"), ("CV (PDF)", "/cv.pdf", "")]


def nav_html(current: str) -> str:
    """The site navigation, with aria-current on the current item."""
    links = []
    for label, href, key in NAV:
        current_attr = ' aria-current="page"' if key and key == current else ""
        links.append(f'      <a href="{href}"{current_attr}>{label}</a>')
    return "\n".join(links)


def fill_template(template: str, fields: dict[str, str]) -> str:
    """Fill templates/base.html; fail if the template asks for a field that has no value."""
    return substitute(template, fields, "templates/base.html")


def text_of(value: object) -> str:
    """Pandoc renders metadata to HTML; strip tags and entities for titles and attributes."""
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def plain_meta(value: object) -> object:
    """Front matter from pandoc with every string reduced to plain text; lists, maps and booleans kept."""
    if isinstance(value, dict):
        return {key: plain_meta(v) for key, v in value.items()}
    if isinstance(value, list):
        return [plain_meta(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    return text_of(value)


def body_class(meta: dict) -> str:
    """' class="home"' for front matter `class: home`, "" without one; anything but a plain class name fails."""
    name = text_of(meta.get("class"))
    if name and not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise BuildError(f"`class: {name}` must be one lowercase class name")
    return f' class="{name}"' if name else ""


def page_fields(*, url: str, meta: dict, body: str, nav: str, css_version: str, feed_link: str,
                year: int) -> dict[str, str]:
    """Values for templates/base.html."""
    title = text_of(meta.get("title")) or "Page not found"
    return {
        "body_class": body_class(meta),
        "title_tag": html.escape(NAME if url == "/" else f"{title} | {NAME}"),
        "description": html.escape(text_of(meta.get("description")) or NAME),
        "canonical": SITE + url,
        "og_type": "profile" if url == "/" else "website",
        "robots": '<meta name="robots" content="noindex">\n' if meta.get("noindex") else "",
        "feed_link": feed_link,
        "css_version": css_version,
        "jsonld": ('<script type="application/ld+json">\n' + json.dumps(JSONLD, indent=2) + "\n</script>\n"
                   if meta.get("jsonld") is True else ""),
        "nav": nav,
        "heading": "" if meta.get("heading") is False else f'<h1 class="page-title">{html.escape(title)}</h1>\n',
        "body": body.strip() + "\n",
        "year": str(year),
    }


def out_path(rel_source: str) -> tuple[str, str]:
    """Map a source path under pages/ (no suffix) to (output file, public URL)."""
    if rel_source == "home":
        return "index.html", "/"
    if rel_source == "404":
        return "404.html", "/404.html"
    return f"{rel_source}/index.html", f"/{rel_source}/"


def now_label(month: str, today: dt.date) -> tuple[str, int]:
    """'2026-10' -> ('October 2026', days since the first of that month)."""
    try:
        first = dt.datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise BuildError(f"`now:` must be YYYY-MM, got {month!r}") from None
    return f"{first:%B} {first.year}", (today - first).days


def redirect_html(target: str, sections: dict[str, str]) -> str:
    """A page that sends visitors from an old address to its new one.

    A one-line script carries old #section links to their new home; without JavaScript the
    meta refresh still lands on the new page.
    """
    script = (f"<script>location.replace({json.dumps(sections)}[location.hash.slice(1)] "
              f"|| {json.dumps(target)});</script>\n")
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<title>Moved</title>\n"
            f"<link rel=\"canonical\" href=\"{SITE + target.split('#')[0]}\">\n"
            + script +
            f"<meta http-equiv=\"refresh\" content=\"0; url={target}\">\n"
            "<meta name=\"robots\" content=\"noindex\">\n</head>\n<body>\n"
            f"<p><a href=\"{target}\">This page has moved.</a></p>\n</body>\n</html>\n")


def missing_anchors(outputs: dict[str, str], addresses: list[str]) -> list[str]:
    """Addresses like "/about/#talks" whose page or #anchor is not among the built outputs."""
    missing = []
    for address in addresses:
        path, _, anchor = address.partition("#")
        page = outputs.get(path.lstrip("/") + "index.html" if path.endswith("/") else path.lstrip("/"))
        if page is None or (anchor and f'id="{anchor}"' not in page):
            missing.append(address)
    return missing


def merge(outputs: dict[str, str], more: dict[str, str]) -> None:
    """Add generated files to outputs; two sources writing the same file is an error."""
    if (clash := sorted(set(outputs) & set(more))):
        raise BuildError(f"two sources generate {', '.join(clash)}")
    outputs.update(more)


def sitemap_xml(urls: list[str]) -> str:
    """sitemap.xml listing the given site-relative URLs, home first."""
    rows = "".join(f"  <url><loc>{SITE}{u}</loc></url>\n" for u in sorted(urls, key=lambda u: (u != "/", u)))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + rows + "</urlset>\n")


def feed_xml(name: str, page: str, feed: str, items: list[FeedItem]) -> str:
    """RSS 2.0 feed. `page` and `feed` are site-relative URLs, e.g. "/writing/" and "/feed.xml"."""
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"{NAME}: {name}"
    ET.SubElement(channel, "link").text = SITE + page
    ET.SubElement(channel, "description").text = f"{name} by {NAME}."
    ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link", href=SITE + feed, rel="self",
                  type="application/rss+xml")
    for it in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = it.title
        ET.SubElement(item, "link").text = it.url
        ET.SubElement(item, "guid", isPermaLink="true").text = it.url
        ET.SubElement(item, "description").text = it.summary
        noon = dt.datetime(it.date.year, it.date.month, it.date.day, 12, tzinfo=dt.timezone.utc)
        ET.SubElement(item, "pubDate").text = email.utils.format_datetime(noon)
    ET.indent(rss)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode") + "\n"


def writing_index(posts: list[Post]) -> str:
    """Body of /writing/: Essays (hosted here), then Published Elsewhere, each newest first or "Coming soon."."""
    here = [post_card(p) for p in posts if not p.external]
    elsewhere = [post_card(p) for p in posts if p.external]
    return "\n".join(['<h2 id="essays">Essays</h2>', card_list(here),
                      '<h2 id="published-elsewhere">Published Elsewhere</h2>', card_list(elsewhere)])


def reading_minutes(body_html: str) -> int:
    """Minutes to read a rendered post: its words / WORDS_PER_MINUTE, rounded up, at least 1.

    Comments and tags are not words; entities are decoded first so "&amp;" is not counted as text.
    """
    text = html.unescape(re.sub(r"<[^>]*>", " ", re.sub(r"<!--.*?-->", " ", body_html, flags=re.S)))
    return max(1, math.ceil(len(text.split()) / WORDS_PER_MINUTE))


def post_meta(p: Post, minutes: int) -> str:
    """The line under a post's title: 'October 8, 2026 • updated November 2, 2026 • 4 min read'."""
    facts = (["Draft"] if p.draft else []) + [long_date(p.date)]
    if p.updated:
        facts.append(f"updated {long_date(p.updated)}")
    facts.append(f"{minutes} min read")
    return f'<p class="meta">{" • ".join(facts)}</p>'


def post_nav(p: Post, posts: list[Post]) -> str:
    """The line under a post: the previous (older) and next (newer) post hosted here, and All writing."""
    here = sorted((q for q in posts if not q.external), key=lambda q: (q.date, q.slug))
    i = here.index(p)
    parts = []
    if i > 0:
        parts.append(f'Previous: <a href="{here[i - 1].url}">{html.escape(here[i - 1].title)}</a>')
    if i < len(here) - 1:
        parts.append(f'Next: <a href="{here[i + 1].url}">{html.escape(here[i + 1].title)}</a>')
    parts.append('<a href="/writing/">All writing</a>')
    return f'<p class="post-nav">{" • ".join(parts)}</p>'


def post_problems(meta: dict) -> list[str]:
    """What is wrong with a post's front matter (strings already plain text); empty when it can be built."""
    problems = [f"missing `{key}`" for key in ("title", "date", "summary") if not meta.get(key)]
    dates = {key: cp.to_date(meta.get(key, "")) for key in ("date", "updated")}
    for key, day in dates.items():
        if meta.get(key) not in (None, "") and day is None:
            problems.append(f"`{key}` must be YYYY-MM-DD, got {meta[key]!r}")
    if dates["date"] and dates["updated"] and dates["updated"] < dates["date"]:
        problems.append("`updated` is earlier than `date`")
    if bool(meta.get("external")) != bool(meta.get("outlet")):
        problems.append("`external` and `outlet` go together: give both or neither")
    return problems


def is_draft(meta: dict) -> bool:
    """True for `draft: true` (YAML's boolean or the word)."""
    return meta.get("draft") is True or str(meta.get("draft")).lower() == "true"


def make_post(path: Path, meta: dict) -> Post:
    """A Post from front matter that has already passed post_problems."""
    return Post(path=path, slug=path.stem, title=str(meta["title"]), summary=str(meta["summary"]),
                date=cp.to_date(meta["date"]), external=str(meta.get("external") or ""),
                outlet=str(meta.get("outlet") or ""), updated=cp.to_date(meta.get("updated", "")),
                draft=is_draft(meta))


# ---------- input and output -------------------------------------------------------------------

def load_config(path: Path = CONFIG) -> dict[str, Path]:
    """Read site.json: paths to files that live outside the repository."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BuildError(f"{path.name} is missing") from None
    return {key: Path(value).expanduser() for key, value in raw.items()}


def read_publications(bib_path: Path) -> Bib:
    """Load and select publications from the bib file."""
    if not bib_path.exists():
        raise BuildError(f"{bib_path} not found (set `bib` in site.json)")
    return select_publications(parse_bib(bib_path.read_text(encoding="utf-8")))


def rel(path: Path) -> str:
    """A path relative to the repository when it is inside it, for messages."""
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def pandoc(path: Path, *args: str) -> str:
    """Render a Markdown file to HTML5 with pandoc."""
    cmd = ["pandoc", str(path), "-f", "markdown", "-t", "html5", "--wrap=none", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as err:
        raise BuildError(f"pandoc failed on {rel(path)}:\n{err.stderr}") from None


def read_meta(path: Path) -> dict:
    """Front matter as a dict (string values arrive rendered as HTML)."""
    return json.loads(pandoc(path, "--template", str(TEMPLATES / "meta.tpl")))


def read_posts(posts_dir: Path, include_drafts: bool = False) -> list[Post]:
    """The posts in posts_dir, newest first; drafts only when include_drafts.

    Every problem in every post's front matter is collected and raised together in one BuildError.
    """
    posts, problems = [], []
    for path in sorted(posts_dir.glob("*.md")):
        meta = plain_meta(read_meta(path))
        if is_draft(meta) and not include_drafts:
            continue
        if (found := post_problems(meta)):
            problems += [f"{rel(path)}: {problem}" for problem in found]
        else:
            posts.append(make_post(path, meta))
    if problems:
        raise BuildError("writing:\n  " + "\n  ".join(problems))
    return sorted(posts, key=lambda p: (p.date, p.slug), reverse=True)


def read_entry(path: Path, topic_slugs: set[str], draft: bool) -> tuple[cp.Entry | None, list[str]]:
    """One commonplace entry, and what stops it from building (the entry is None when anything does).

    Leftovers from staging (CHECK comments, [[wikilinks]]) stop a published entry; in a draft they
    are printed as warnings and the draft is still built.
    """
    meta = plain_meta(read_meta(path))
    problems = cp.entry_problems(path.stem, meta, topic_slugs)
    leftovers = cp.text_problems(path.read_text(encoding="utf-8"))
    if draft:
        for leftover in leftovers:
            print(f"warning: {rel(path)}: {leftover}", file=sys.stderr)
    else:
        problems += leftovers
    entry = None if problems else cp.make_entry(path.stem, meta, path, draft)
    return entry, [f"{rel(path)}: {p}" for p in problems]


def read_book(preview: bool, book_dir: Path = BOOK, entries_dir: Path = ENTRIES,
              drafts_dir: Path = DRAFT_ENTRIES) -> cp.Book:
    """Read the commonplace book: its config, the published entries and, when previewing, the drafts.

    Every problem in the config and the entries is collected and raised together in one
    BuildError, so a single build lists them all.
    """
    index = book_dir / "index.md"
    config = plain_meta(read_meta(index))
    topics, trails = cp.parse_config(config)
    topic_slugs = {t.slug for t in topics}
    published = sorted(entries_dir.glob("*.md"))
    drafts = sorted(drafts_dir.glob("*.md")) if preview else []
    entries, problems = [], []
    for path, draft in [(p, False) for p in published] + [(p, True) for p in drafts]:
        entry, found = read_entry(path, topic_slugs, draft)
        problems += found
        if entry:
            entries.append(entry)
    for slug in sorted({p.stem for p in published} & {p.stem for p in drafts}):
        problems.append(f"{slug!r} is both published ({rel(entries_dir)}) and drafted ({rel(drafts_dir)})")
    # Check paths against every entry file, so one broken entry is not also reported as missing.
    slugs = {p.stem for p in published + drafts}
    problems += [f"{rel(index)}: {p}" for p in cp.config_problems(topics, trails, slugs)]
    title, description = str(config.get("title") or ""), str(config.get("description") or "")
    if not (title and description):
        problems.append(f"{rel(index)} needs `title` and `description` in its front matter")
    if problems:
        raise BuildError("commonplace:\n  " + "\n  ".join(problems))
    return cp.Book(title=title, description=description, intro=pandoc(index), topics=topics,
                   trails=trails, entries=tuple(entries))


def write_outputs(outputs: dict[str, str], root: Path = ROOT) -> list[str]:
    """Write files whose contents changed; return their paths."""
    changed = []
    for rel, text in outputs.items():
        path = root / rel
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            changed.append(rel)
    return changed


def write_preview(outputs: dict[str, str], out: Path = PREVIEW_OUT, drafts: Path = DRAFTS) -> None:
    """Replace the preview folder with this build's files.

    Only `out` is deleted, and only after checking that it lies inside `drafts`, so a wrong
    constant can never delete staged drafts or anything in the repository.
    """
    if not out.resolve().is_relative_to(drafts.resolve()) or out.resolve() == drafts.resolve():
        raise BuildError(f"preview folder {out} must be inside {drafts}; nothing written")
    if out.exists():
        shutil.rmtree(out)
    write_outputs(outputs, out)


PROTECTED_DIRS = {".git", "pages", "templates", "tools", "tests", "writing/posts", "commonplace/entries", "drafts"}


def prunable(rel: str, root: Path = ROOT) -> bool:
    """True only for a generated-looking file (.html or .xml) safely inside the repository.

    Guards against a hand-edited or corrupted manifest pointing at sources or at files outside
    the repository.
    """
    path = Path(rel)
    if path.as_posix() != rel:  # "./x", "a//b": the build never writes these, so the manifest was edited
        return False
    if path.is_absolute() or ".." in path.parts or path.suffix not in {".html", ".xml"}:
        return False
    if any(rel == d or rel.startswith(d + "/") for d in PROTECTED_DIRS):
        return False
    try:
        (root / path).resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def prune_stale(outputs: dict[str, str], manifest: Path = MANIFEST, root: Path = ROOT) -> list[str]:
    """Delete files the previous build made that this build did not, then update the manifest.

    The manifest has one path per line. Entries that fail `prunable` are reported and kept.
    """
    previous = {line.strip() for line in manifest.read_text().splitlines() if line.strip()} if manifest.exists() else set()
    removed = []
    for rel in sorted(previous - set(outputs)):
        if not prunable(rel, root):
            print(f"warning: build-manifest.txt lists {rel!r}, which is not a generated file; left alone",
                  file=sys.stderr)
            continue
        path = root / rel
        if path.is_file():
            path.unlink()
            removed.append(rel)
            parent = path.parent
            while parent != root and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
    listing = "".join(f"{rel}\n" for rel in sorted(outputs))
    if not manifest.exists() or manifest.read_text() != listing:
        manifest.write_text(listing)
    return removed


# ---------- build steps ------------------------------------------------------------------------

def build_pages(base: str, pubs: Bib, sections: dict[str, str],
                common: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Render every page under pages/; return (outputs, sitemap URLs).

    `sections` fills the <!-- writing:recent --> and <!-- commonplace:recent --> tokens.
    """
    outputs, urls, today = {}, [], dt.date.today()
    for src in sorted(PAGES.rglob("*.md")):
        where = rel(src)
        out_file, url = out_path(src.relative_to(PAGES).with_suffix("").as_posix())
        meta = read_meta(src)
        if src.stem != "404" and not (meta.get("title") and meta.get("description")):
            raise BuildError(f"{where} needs `title` and `description` in its front matter")
        ctx = {"pub_count": str(len(pubs))}
        if meta.get("now"):
            ctx["now"], age = now_label(text_of(meta["now"]), today)
            if age > NOW_MAX_DAYS:
                print(f"warning: {where}: the Now section says {ctx['now']}; update it", file=sys.stderr)
        if src.stem == "404":
            meta["noindex"] = True
        else:
            urls.append(url)
        body = expand_tokens(pandoc(src), pubs, ctx, where, sections)
        nav = nav_html(text_of(meta.get("nav")))
        outputs[out_file] = fill_template(base, page_fields(url=url, meta=meta, body=body, nav=nav,
                                                            year=today.year, **common))
    return outputs, urls


def post_body(p: Post, posts: list[Post], pubs: Bib) -> str:
    """A post page's body: the date and reading-time line, the rendered text, then Previous and Next."""
    text = expand_tokens(pandoc(p.path), pubs, {}, rel(p.path))
    return post_meta(p, reading_minutes(text)) + "\n" + text.strip() + "\n" + post_nav(p, posts)


def build_writing(base: str, pubs: Bib, posts: list[Post],
                  common: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Render /writing/ (always), a page for each post hosted here, and the feed once there are posts.

    Returns (outputs, sitemap URLs).
    """
    pages = [("/writing/", {"title": "Writing", "description": f"Essays by {NAME}."}, writing_index(posts))]
    pages += [(p.url, {"title": p.title, "description": p.summary}, post_body(p, posts, pubs))
              for p in posts if not p.external]
    nav, year = nav_html("writing"), dt.date.today().year
    outputs = {url.lstrip("/") + "index.html":
               fill_template(base, page_fields(url=url, meta=meta, body=body, nav=nav, year=year, **common))
               for url, meta, body in pages}
    if posts:
        items = [FeedItem(p.title, p.external or SITE + p.url, p.summary, p.date) for p in posts]
        outputs["feed.xml"] = feed_xml("Writing", "/writing/", "/feed.xml", items)
    return outputs, [url for url, _, _ in pages]


def entry_body(e: cp.Entry, book: cp.Book, pubs: Bib) -> str:
    """An entry page's body: breadcrumb, title and dates, the rendered text, then related entries.

    Math is rendered to MathML, which browsers display without JavaScript.
    """
    text = expand_tokens(pandoc(e.source, "--mathml"), pubs, {}, rel(e.source))
    return cp.entry_head(e, {t.slug: t for t in book.topics}) + text.strip() + "\n" + cp.entry_foot(e, book)


def build_commonplace(base: str, pubs: Bib, book: cp.Book,
                      common: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Render the index and every topic page (always), then the entries, reading paths and feed if any.

    Returns (outputs, sitemap URLs).
    """
    by_slug = {e.slug: e for e in book.entries}
    # (url, front matter, body). Topic and entry pages write their own h1 below a breadcrumb.
    pages = [("/commonplace/", {"title": book.title, "description": book.description}, cp.index_body(book))]
    for t in book.topics:
        about = f"Entries on {t.title} in {NAME}'s commonplace book."
        pages.append((t.url, {"title": t.title, "description": about, "heading": False},
                      cp.topic_body(t, book.entries)))
    for e in book.entries:
        pages.append((e.url, {"title": e.title, "description": e.summary, "heading": False},
                      entry_body(e, book, pubs)))
    for t in book.trails:
        if t.entries:
            about = f"A reading path in {NAME}'s commonplace book: {cp.count_label(len(t.entries))}, in order."
            pages.append((t.url, {"title": t.title, "description": about}, cp.trail_body(t, by_slug)))
    nav, year = nav_html("commonplace"), dt.date.today().year
    outputs = {url.lstrip("/") + "index.html":
               fill_template(base, page_fields(url=url, meta=meta, body=body, nav=nav, year=year, **common))
               for url, meta, body in pages}
    if book.entries:
        items = [FeedItem(e.title, SITE + e.url, e.summary, e.added) for e in cp.newest_first(book.entries)]
        outputs["commonplace/feed.xml"] = feed_xml(book.title, "/commonplace/", "/commonplace/feed.xml", items)
    return outputs, [url for url, _, _ in pages]


def feed_links(writing: bool, commonplace: bool) -> str:
    """<link rel="alternate"> tags for the head of every page."""
    links = []
    if writing:
        links.append('<link rel="alternate" type="application/rss+xml" title="Writing" href="/feed.xml">\n')
    if commonplace:
        links.append('<link rel="alternate" type="application/rss+xml" title="Commonplace" '
                     'href="/commonplace/feed.xml">\n')
    return "".join(links)


def build(preview: bool = False) -> tuple[dict[str, str], Bib, list[Post], cp.Book]:
    """Render the whole site into a {path: contents} map without writing anything.

    With preview, drafts are included (writing drafts and drafts/commonplace/).
    """
    if not shutil.which("pandoc"):
        raise BuildError("pandoc is not installed")
    config = load_config()
    pubs = read_publications(config["bib"])
    posts = read_posts(POSTS, include_drafts=preview)
    if preview:   # drafts/writing/ is gitignored, so unpublished essays never reach the public repository
        posts = sorted(posts + read_posts(DRAFT_POSTS, include_drafts=True), key=lambda p: (p.date, p.slug), reverse=True)
    book = read_book(preview, BOOK, ENTRIES, DRAFT_ENTRIES)
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    common = {
        "css_version": hashlib.sha1((ROOT / "style.css").read_bytes()).hexdigest()[:8],
        "feed_link": feed_links(bool(posts), bool(book.entries)),
    }
    sections = {"writing": writing_recent(posts), "commonplace": commonplace_recent(book.entries)}
    outputs, urls = build_pages(base, pubs, sections, common)
    writing, writing_urls = build_writing(base, pubs, posts, common)
    merge(outputs, writing)
    commonplace, book_urls = build_commonplace(base, pubs, book, common)
    merge(outputs, commonplace)
    merge(outputs, {old: redirect_html(new, sections) for old, (new, sections) in REDIRECTS.items()})
    targets = [new for new, sections in REDIRECTS.values()] + [t for _, s in REDIRECTS.values() for t in s.values()]
    if (missing := missing_anchors(outputs, targets)):
        raise BuildError(f"redirects point at missing pages or anchors: {', '.join(missing)}")
    merge(outputs, {"sitemap.xml": sitemap_xml(urls + writing_urls + book_urls)})
    return outputs, pubs, posts, book


def main(argv: list[str] | None = None) -> int:
    """Build; write changed files, prune stale ones and report, or with --preview write drafts/_site."""
    parser = argparse.ArgumentParser(description="Build garrettthrash.com from its Markdown sources.")
    parser.add_argument("--preview", action="store_true",
                        help="include drafts and write everything to drafts/_site (never the repository)")
    args = parser.parse_args(argv)
    try:
        outputs, pubs, posts, book = build(preview=args.preview)
        if args.preview:
            write_preview(outputs)
    except (BuildError, cp.CommonplaceError) as err:
        print(f"build.py: {err}", file=sys.stderr)
        return 1
    if args.preview:
        drafts = sum(e.draft for e in book.entries)
        print(f"preview: {len(outputs)} files in {rel(PREVIEW_OUT)}; {len(posts)} posts (drafts included); "
              f"{len(book.entries)} commonplace entries ({drafts} drafts). Serve with: python3 tools/serve.py 8000")
        return 0
    changed = write_outputs(outputs)
    removed = prune_stale(outputs)
    for path in changed:
        print("updated", path)
    for path in removed:
        print("removed", path)
    print(f"{len(outputs)} files; {len(pubs)} publications; {len(posts)} published posts; "
          f"{len(book.entries)} commonplace entries; {len(changed)} updated, {len(removed)} removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
