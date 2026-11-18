#!/usr/bin/env python3
"""Build garrettthrash.com from Markdown sources with pandoc. Never runs git.

Sources and what they become:
    pages/home.md               -> index.html
    pages/404.md                -> 404.html
    pages/<name>.md             -> <name>/index.html
    pages/projects/<slug>.md    -> projects/<slug>/index.html
    writing/posts/<slug>.md     -> writing/<slug>/index.html, writing/index.html, feed.xml
                                   (nothing is generated until a post drops `draft: true`)
Also generated: redirect pages for the old addresses, sitemap.xml, build-manifest.txt.

Page front matter: `title` and `description` (required), `nav` (the current nav item),
`heading: false` (the page writes its own h1), `jsonld: true` (home only),
`now: YYYY-MM` (the About page's Now section).

Tokens a page body can use; they are replaced after pandoc renders the page:
    <!-- pubs:all -->             every peer-reviewed publication, newest first
    <!-- pubs:keys k1 k2 ... -->  the listed bib keys, newest first
    {{pub_count}}                 number of peer-reviewed publications
    {{now}}                       the `now:` month spelled out, e.g. "October 2026"

Publications come from the Better BibTeX export named in site.json (the same file the LaTeX CV
uses). The rules mirror the CV: "Correction to:" errata dropped, newest first, owner in bold.

Usage: python3 build.py        Needs Python 3.9+ and pandoc.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = "https://garrettthrash.com"
NAME = "Garrett W. Thrash"
PAGES = ROOT / "pages"
POSTS = ROOT / "writing" / "posts"
TEMPLATES = ROOT / "templates"
CONFIG = ROOT / "site.json"
MANIFEST = ROOT / "build-manifest.txt"

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
WRITING_NAV_AT = 3         # Writing joins the navigation at this many published posts

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
    """One piece of writing from writing/posts/."""
    path: Path
    slug: str
    title: str
    summary: str
    date: dt.date
    external: str = ""
    outlet: str = ""


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


def fmt_ids(entry: dict[str, str]) -> str:
    """DOI and PubMed links, or an empty string."""
    links = []
    if entry.get("doi"):
        links.append(f'<a href="https://doi.org/{html.escape(plain(entry["doi"]))}">doi</a>')
    pmid = plain(entry["eprint"]) if entry.get("eprinttype", "").lower() == "pubmed" and entry.get("eprint") \
        else plain(entry.get("pmid", ""))
    if pmid:
        links.append(f'<a href="https://pubmed.ncbi.nlm.nih.gov/{html.escape(pmid)}/">pubmed</a>')
    return f' <span class="ids">{"".join(links)}</span>' if links else ""


def fmt_pub(entry: dict[str, str]) -> str:
    """One reference as a CV-style entry: year on the left, citation on the right."""
    title = html.escape(plain(entry.get("title", "")))
    if title and title[-1] not in ".?!":
        title += "."
    return (f'<div class="entry ref"><p>{pub_date(entry)[0]}</p>'
            f'<p>{fmt_authors(entry.get("author", ""))} <span class="t">{title}</span> '
            f'{fmt_source(entry)}.{fmt_ids(entry)}</p></div>')


# ---------- page assembly (pure) ---------------------------------------------------------------

def expand_tokens(body: str, pubs: Bib, ctx: dict[str, str], where: str) -> str:
    """Replace publication and {{name}} tokens in rendered HTML; fail on unknown keys or leftovers."""
    def keyed(m: re.Match) -> str:
        wanted = m.group(1).split()
        missing = [k for k in wanted if k not in pubs]
        if missing:
            raise BuildError(f"{where}: unknown bib key(s): {', '.join(missing)}")
        return "\n".join(fmt_pub(e) for e in sorted((pubs[k] for k in wanted), key=pub_date, reverse=True))

    body = substitute(body, ctx, where)
    body = re.sub(r"<!--\s*pubs:keys\s+(.*?)\s*-->", keyed, body)
    body = re.sub(r"<!--\s*pubs:all\s*-->", lambda _: "\n".join(fmt_pub(e) for e in pubs.values()), body)
    if (left := re.search(r"<!--\s*pubs:", body)):
        raise BuildError(f"{where}: malformed publication token {left.group(0)}")
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


def nav_html(current: str, show_writing: bool) -> str:
    """The site navigation, with aria-current on the current item."""
    items = [("Research", "/research/", "research")]
    if show_writing:
        items.append(("Writing", "/writing/", "writing"))
    items += [("About &amp; CV", "/about/", "about"), ("CV (PDF)", "/cv.pdf", "")]
    links = []
    for label, href, key in items:
        current_attr = ' aria-current="page"' if key and key == current else ""
        links.append(f'      <a href="{href}"{current_attr}>{label}</a>')
    return "\n".join(links)


def fill_template(template: str, fields: dict[str, str]) -> str:
    """Fill templates/base.html; fail if the template asks for a field that has no value."""
    return substitute(template, fields, "templates/base.html")


def text_of(value: object) -> str:
    """Pandoc renders metadata to HTML; strip tags and entities for titles and attributes."""
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def page_fields(*, url: str, meta: dict, body: str, nav: str, css_version: str, feed_link: str,
                year: int) -> dict[str, str]:
    """Values for templates/base.html."""
    title = text_of(meta.get("title")) or "Page not found"
    return {
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


def long_date(d: dt.date) -> str:
    """January 12, 2027."""
    return f"{d:%B} {d.day}, {d.year}"


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


def feed_xml(posts: list[Post]) -> str:
    """RSS 2.0 feed of published writing."""
    rss = ET.Element("rss", version="2.0", attrib={"xmlns:atom": "http://www.w3.org/2005/Atom"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"{NAME}: Writing"
    ET.SubElement(channel, "link").text = f"{SITE}/writing/"
    ET.SubElement(channel, "description").text = f"Writing by {NAME}."
    ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link", href=f"{SITE}/feed.xml", rel="self",
                  type="application/rss+xml")
    for p in posts:
        url = p.external or f"{SITE}/writing/{p.slug}/"
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = p.title
        ET.SubElement(item, "link").text = url
        ET.SubElement(item, "guid", isPermaLink="true").text = url
        ET.SubElement(item, "description").text = p.summary
        noon = dt.datetime(p.date.year, p.date.month, p.date.day, 12, tzinfo=dt.timezone.utc)
        ET.SubElement(item, "pubDate").text = email.utils.format_datetime(noon)
    ET.indent(rss)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding="unicode") + "\n"


def writing_index(posts: list[Post]) -> str:
    """Body of /writing/: one dated entry per post."""
    rows = []
    for p in posts:
        href = p.external or f"/writing/{p.slug}/"
        outlet = f" • <em>{html.escape(p.outlet)}</em>" if p.outlet else ""
        rows.append(f'<div class="entry"><p>{long_date(p.date)}</p>'
                    f'<p><a href="{html.escape(href)}">{html.escape(p.title)}</a>{outlet}</p></div>')
    return "\n".join(rows)


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


def pandoc(path: Path, *args: str) -> str:
    """Render a Markdown file to HTML5 with pandoc."""
    cmd = ["pandoc", str(path), "-f", "markdown", "-t", "html5", "--wrap=none", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as err:
        raise BuildError(f"pandoc failed on {path.relative_to(ROOT)}:\n{err.stderr}") from None


def read_meta(path: Path) -> dict:
    """Front matter as a dict (string values arrive rendered as HTML)."""
    return json.loads(pandoc(path, "--template", str(TEMPLATES / "meta.tpl")))


def read_post(path: Path) -> Post | None:
    """A Post, or None if it is a draft."""
    meta = read_meta(path)
    if meta.get("draft") is True or text_of(meta.get("draft")).lower() == "true":
        return None
    title, summary, date = (text_of(meta.get(k)) for k in ("title", "summary", "date"))
    if not (title and summary and date):
        raise BuildError(f"{path.relative_to(ROOT)}: title, date and summary are required")
    try:
        day = dt.date.fromisoformat(date)
    except ValueError:
        raise BuildError(f"{path.relative_to(ROOT)}: date must be YYYY-MM-DD, got {date!r}") from None
    return Post(path, path.stem, title, summary, day, text_of(meta.get("external")), text_of(meta.get("outlet")))


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


PROTECTED_DIRS = {".git", "pages", "templates", "tools", "tests", "writing/posts"}


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

def build_pages(base: str, pubs: Bib, nav_writing: bool, common: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Render every page under pages/; return (outputs, sitemap URLs)."""
    outputs, urls, today = {}, [], dt.date.today()
    for src in sorted(PAGES.rglob("*.md")):
        where = str(src.relative_to(ROOT))
        rel, url = out_path(src.relative_to(PAGES).with_suffix("").as_posix())
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
        body = expand_tokens(pandoc(src), pubs, ctx, where)
        nav = nav_html(text_of(meta.get("nav")), nav_writing)
        outputs[rel] = fill_template(base, page_fields(url=url, meta=meta, body=body, nav=nav,
                                                       year=today.year, **common))
    return outputs, urls


def build_writing(base: str, pubs: Bib, posts: list[Post], nav_writing: bool,
                  common: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Render published posts, the Writing index and the feed; nothing when there are no posts."""
    if not posts:
        return {}, []
    outputs, urls, year = {}, [], dt.date.today().year
    nav = nav_html("writing", nav_writing)
    for p in posts:
        if p.external:
            continue
        body = (f'<p class="meta"><em>{long_date(p.date)}</em></p>\n'
                + expand_tokens(pandoc(p.path), pubs, {}, str(p.path.relative_to(ROOT))))
        meta = {"title": p.title, "description": p.summary}
        url = f"/writing/{p.slug}/"
        outputs[f"writing/{p.slug}/index.html"] = fill_template(
            base, page_fields(url=url, meta=meta, body=body, nav=nav, year=year, **common))
        urls.append(url)
    meta = {"title": "Writing", "description": f"Essays by {NAME}."}
    outputs["writing/index.html"] = fill_template(
        base, page_fields(url="/writing/", meta=meta, body=writing_index(posts), nav=nav, year=year, **common))
    outputs["feed.xml"] = feed_xml(posts)
    return outputs, urls + ["/writing/"]


def build() -> tuple[dict[str, str], Bib, list[Post]]:
    """Render the whole site into a {path: contents} map without writing anything."""
    if not shutil.which("pandoc"):
        raise BuildError("pandoc is not installed")
    config = load_config()
    pubs = read_publications(config["bib"])
    posts = sorted(filter(None, (read_post(p) for p in sorted(POSTS.glob("*.md")))),
                   key=lambda p: (p.date, p.slug), reverse=True)
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    nav_writing = len(posts) >= WRITING_NAV_AT
    common = {
        "css_version": hashlib.sha1((ROOT / "style.css").read_bytes()).hexdigest()[:8],
        "feed_link": ('<link rel="alternate" type="application/rss+xml" title="Writing" href="/feed.xml">\n'
                      if posts else ""),
    }
    outputs, urls = build_pages(base, pubs, nav_writing, common)
    writing, writing_urls = build_writing(base, pubs, posts, nav_writing, common)
    merge(outputs, writing)
    merge(outputs, {old: redirect_html(new, sections) for old, (new, sections) in REDIRECTS.items()})
    targets = [new for new, sections in REDIRECTS.values()] + [t for _, s in REDIRECTS.values() for t in s.values()]
    if (missing := missing_anchors(outputs, targets)):
        raise BuildError(f"redirects point at missing pages or anchors: {', '.join(missing)}")
    merge(outputs, {"sitemap.xml": sitemap_xml(urls + writing_urls)})
    return outputs, pubs, posts


def main() -> int:
    """Build, write changed files, prune stale ones, and report."""
    try:
        outputs, pubs, posts = build()
    except BuildError as err:
        print(f"build.py: {err}", file=sys.stderr)
        return 1
    changed = write_outputs(outputs)
    removed = prune_stale(outputs)
    for rel in changed:
        print("updated", rel)
    for rel in removed:
        print("removed", rel)
    print(f"{len(outputs)} files; {len(pubs)} publications; {len(posts)} published posts; "
          f"{len(changed)} updated, {len(removed)} removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
