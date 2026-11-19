"""The commonplace book: entries, topics and reading paths, rendered to HTML. Pure functions only.

build.py reads the files and calls these functions. tools/stage.py and tools/promote.py use the same
checks, so an entry that promotes cleanly also builds.

Sources:
    commonplace/index.md             front matter lists the topics and the reading paths; its body,
                                     if any, is the introduction on /commonplace/
    commonplace/entries/<slug>.md    published entries
    drafts/commonplace/<slug>.md     staged drafts (git ignores drafts/); only `build.py --preview`
                                     shows them

Entry front matter:
    title: Band power and the aperiodic exponent
    summary: One sentence, used on Home, in search results and in the feed.
    type: note                       note, derivation, code or reading; or a list: [derivation, code]
    topics: [signal-processing]      topic slugs from commonplace/index.md
    added: 2027-01-12
    updated: 2027-02-03              optional

Pages: /commonplace/ (the topic directory) and one page per topic, /commonplace/topics/<slug>/, are
always built; a topic with no entries says "Coming soon.". Entry pages, reading-path pages and the feed
are built only for entries that exist.
"""
from __future__ import annotations

import datetime as dt
import html
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

RELATED_MAX = 3            # related entries listed under each entry
INDEX_RECENT = 5           # newest entries listed under Recent on /commonplace/
TYPES = {"note": "Note", "derivation": "Derivation", "code": "Code", "reading": "Reading"}
REQUIRED = ("title", "summary", "type", "topics", "added")
RESERVED_SLUGS = {"entries", "images", "paths", "topics"}   # folder names under commonplace/
CHECK = "CHECK:"           # tools/stage.py leaves <!-- CHECK: ... --> comments; none may publish
COMING_SOON = "<p>Coming soon.</p>"   # the only placeholder text on the site

Meta = dict[str, object]   # front matter with every string already reduced to plain text


class CommonplaceError(ValueError):
    """A problem in the commonplace sources that should stop the build."""


@dataclass(frozen=True)
class Topic:
    """A topic: a line in the index's directory and a page of its own.

    `vault` is the PhD Vault folder whose notes default to this topic when staged.
    """
    slug: str
    title: str
    vault: str = ""

    @property
    def url(self) -> str:
        return f"/commonplace/topics/{self.slug}/"


@dataclass(frozen=True)
class Trail:
    """A reading path: entries meant to be read in order."""
    slug: str
    title: str
    entries: tuple[str, ...]

    @property
    def url(self) -> str:
        return f"/commonplace/paths/{self.slug}/"


@dataclass(frozen=True)
class Entry:
    """One commonplace entry, read from its front matter."""
    slug: str
    title: str
    summary: str
    types: tuple[str, ...]
    topics: tuple[str, ...]
    added: dt.date
    updated: dt.date | None
    source: Path
    draft: bool = False

    @property
    def url(self) -> str:
        return f"/commonplace/{self.slug}/"


@dataclass(frozen=True)
class Book:
    """Everything the commonplace pages are built from."""
    title: str
    description: str
    intro: str                     # rendered HTML of commonplace/index.md's body, often empty
    topics: tuple[Topic, ...]
    trails: tuple[Trail, ...]
    entries: tuple[Entry, ...]


# ---------- small helpers ----------------------------------------------------------------------

def long_date(d: dt.date) -> str:
    """January 12, 2027."""
    return f"{d:%B} {d.day}, {d.year}"


def short_date(d: dt.date) -> str:
    """Jan 2027."""
    return f"{d:%b} {d.year}"


def slugify(title: str) -> str:
    """'Band power and the 1/f exponent' -> 'band-power-and-the-1-f-exponent'."""
    ascii_text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def as_list(value: object) -> list[str]:
    """A front-matter value as a list of strings: 'note' -> ['note'], None -> []."""
    if value is None or value == "":
        return []
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def to_date(value: object) -> dt.date | None:
    """'2027-01-12' -> date, or None if it is not a YYYY-MM-DD date."""
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def type_label(types: tuple[str, ...]) -> str:
    """('derivation', 'code') -> 'Derivation and code'."""
    words = [TYPES[types[0]]] + [TYPES[t].lower() for t in types[1:]]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


# ---------- checks -----------------------------------------------------------------------------

def entry_problems(slug: str, meta: Meta, topic_slugs: set[str]) -> list[str]:
    """What is wrong with an entry's file name and front matter; empty when it can be built."""
    problems = [f"missing `{key}`" for key in REQUIRED if not as_list(meta.get(key))]
    if slug != slugify(slug):
        problems.append(f"file name {slug!r} must be lowercase words joined by hyphens")
    if slug in RESERVED_SLUGS:
        problems.append(f"file name {slug!r} is reserved")
    problems += [f"unknown type {t!r} (use {', '.join(TYPES)})" for t in as_list(meta.get("type")) if t not in TYPES]
    problems += [f"unknown topic {t!r} (add it to commonplace/index.md)"
                 for t in as_list(meta.get("topics")) if t not in topic_slugs]
    for key in ("added", "updated"):
        value = meta.get(key)
        if value is not None and value != "" and to_date(value) is None:   # catches `added: false` too
            problems.append(f"`{key}` must be YYYY-MM-DD, got {value!r}")
    added, updated = to_date(meta.get("added", "")), to_date(meta.get("updated", ""))
    if added and updated and updated < added:
        problems.append("`updated` is earlier than `added`")
    return problems


FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def code_mask(lines: list[str]) -> tuple[list[bool], bool]:
    """(True for each line of a fenced code block, fences included; whether a fence is left open).

    A fence closes on a line of the same character at least as long as the opening run, with nothing
    after it, as in CommonMark. tools/stage.py uses this too, so staging and promotion agree on what
    counts as code.
    """
    mask, fence = [], ""
    for line in lines:
        m = FENCE.match(line)
        if fence:
            mask.append(True)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                fence = ""
        elif m and not (m.group(1)[0] == "`" and "`" in m.group(2)):   # ``` with a backtick after it is not a fence
            mask.append(True)
            fence = m.group(1)
        else:
            mask.append(False)
    return mask, bool(fence)


def without_code(text: str) -> str:
    """Markdown with fenced code blocks and `inline code` removed, so code like a[[0, 1]] is ignored."""
    lines = text.split("\n")
    mask, _ = code_mask(lines)
    prose = "\n".join(line for line, in_code in zip(lines, mask) if not in_code)
    return re.sub(r"`[^`\n]*`", "", prose)


def text_problems(text: str) -> list[str]:
    """Leftovers from staging in an entry's Markdown source."""
    problems = []
    if (n := text.count(CHECK)):
        problems.append(f"{n} CHECK comment(s) left from staging")
    if code_mask(text.split("\n"))[1]:
        problems.append("a code fence is never closed")
    if "[[" in without_code(text):
        problems.append("vault wikilinks ([[...]]) left in the text")
    return problems


def make_entry(slug: str, meta: Meta, source: Path, draft: bool = False) -> Entry:
    """Build an Entry from front matter that has already passed entry_problems."""
    return Entry(slug=slug, title=str(meta["title"]), summary=str(meta["summary"]),
                 types=tuple(as_list(meta["type"])), topics=tuple(as_list(meta["topics"])),
                 added=to_date(meta["added"]), updated=to_date(meta.get("updated", "")),
                 source=source, draft=draft)


def parse_config(meta: Meta) -> tuple[tuple[Topic, ...], tuple[Trail, ...]]:
    """Topics and reading paths from commonplace/index.md's front matter."""
    def text(item: object, key: str) -> str:
        return str(item.get(key, "")) if isinstance(item, dict) else ""
    topics = tuple(Topic(text(t, "slug"), text(t, "title"), text(t, "vault")) for t in meta.get("topics") or [])
    trails = tuple(Trail(text(p, "slug"), text(p, "title"),
                         tuple(as_list(p.get("entries")) if isinstance(p, dict) else []))
                   for p in meta.get("paths") or [])
    return topics, trails


def config_problems(topics: tuple[Topic, ...], trails: tuple[Trail, ...], entry_slugs: set[str]) -> list[str]:
    """Duplicate or malformed topics and paths, and paths that list entries that don't exist."""
    problems = []
    for kind, items in (("topic", topics), ("path", trails)):
        slugs = [item.slug for item in items]
        problems += [f"{kind} {s!r} is listed twice" for s in sorted({s for s in slugs if slugs.count(s) > 1})]
        problems += [f"each {kind} needs a lowercase-hyphen `slug` and a `title` (got slug {item.slug!r})"
                     for item in items if not item.slug or item.slug != slugify(item.slug) or not item.title]
    for trail in trails:
        problems += [f"path {trail.slug!r} lists {s!r}, which is not an entry" for s in trail.entries
                     if s not in entry_slugs]
        if len(set(trail.entries)) != len(trail.entries):
            problems.append(f"path {trail.slug!r} lists an entry twice")
    return problems


# ---------- ordering ---------------------------------------------------------------------------

def newest_first(entries: tuple[Entry, ...]) -> list[Entry]:
    """Entries by date added, newest first; ties by title."""
    return sorted(entries, key=lambda e: (-e.added.toordinal(), e.title.lower()))


def related(entry: Entry, entries: tuple[Entry, ...], n: int = RELATED_MAX) -> list[Entry]:
    """Up to n other entries sharing a topic with `entry`: most shared topics first, then newest."""
    shared = [(len(set(entry.topics) & set(other.topics)), other) for other in entries if other.slug != entry.slug]
    shared = [(count, other) for count, other in shared if count]
    shared.sort(key=lambda pair: (-pair[0], -pair[1].added.toordinal(), pair[1].title.lower()))
    return [other for _, other in shared[:n]]


# ---------- HTML -------------------------------------------------------------------------------

def entry_row(e: Entry) -> str:
    """An index line: month on the left, title and type on the right."""
    return (f'<div class="entry"><p>{short_date(e.added)}</p>'
            f'<p><a href="{e.url}">{html.escape(e.title)}</a></p>'
            f'<p class="kind">{type_label(e.types)}</p></div>')


def count_label(n: int) -> str:
    """1 -> '1 entry', 4 -> '4 entries'."""
    return f"{n} entry" if n == 1 else f"{n} entries"


def in_topic(topic: Topic, entries: tuple[Entry, ...]) -> list[Entry]:
    """The entries filed under a topic, newest first."""
    return [e for e in newest_first(entries) if topic.slug in e.topics]


def topic_row(topic: Topic, entries: tuple[Entry, ...]) -> str:
    """A directory line: the entry count (or "Coming soon.") on the left, the linked topic on the right."""
    n = len(in_topic(topic, entries))
    count = count_label(n) if n else "Coming soon."
    return f'<div class="entry topic"><p>{count}</p><p><a href="{topic.url}">{html.escape(topic.title)}</a></p></div>'


def index_body(book: Book) -> str:
    """The body of /commonplace/: the introduction, every topic, then Recent and Paths when they have anything."""
    parts = [book.intro.strip()] if book.intro.strip() else []
    parts.append('<h2 id="topics">Topics</h2>')
    parts += [topic_row(t, book.entries) for t in book.topics]
    if book.entries:
        parts.append('<h2 id="recent">Recent</h2>')
        parts += [entry_row(e) for e in newest_first(book.entries)[:INDEX_RECENT]]
    if (trails := [t for t in book.trails if t.entries]):
        parts.append('<h2 id="paths">Paths</h2>')
        parts += [f'<div class="entry"><p>{count_label(len(t.entries))}</p>'
                  f'<p><a href="{t.url}">{html.escape(t.title)}</a></p></div>' for t in trails]
    return "\n".join(parts)


def topic_body(topic: Topic, entries: tuple[Entry, ...]) -> str:
    """A topic's page: a breadcrumb, the topic as the h1, then its entries newest first or "Coming soon."."""
    rows = [entry_row(e) for e in in_topic(topic, entries)] or [COMING_SOON]
    return ('<p class="crumb"><a href="/commonplace/">Commonplace</a></p>\n'
            f'<h1 class="page-title">{html.escape(topic.title)}</h1>\n' + "\n".join(rows))


def entry_head(e: Entry, topics: dict[str, Topic]) -> str:
    """Breadcrumb (the book, then each of the entry's topic pages), title and dates above an entry's text."""
    crumbs = ['<a href="/commonplace/">Commonplace</a>'] + [
        f'<a href="{topics[slug].url}">{html.escape(topics[slug].title)}</a>' for slug in e.topics]
    facts = (["Draft"] if e.draft else []) + [type_label(e.types), long_date(e.added)]
    if e.updated:
        facts.append(f"updated {long_date(e.updated)}")
    return (f'<p class="crumb">{" • ".join(crumbs)}</p>\n'
            f'<h1 class="page-title">{html.escape(e.title)}</h1>\n'
            f'<p class="meta">{" • ".join(facts)}</p>\n')


def trail_nav(e: Entry, trails: tuple[Trail, ...], by_slug: dict[str, Entry]) -> list[str]:
    """'Reading a power spectrum, 2 of 4 • Previous: ... • Next: ...' for each path holding e."""
    lines = []
    for trail in trails:
        if e.slug not in trail.entries:
            continue
        i = trail.entries.index(e.slug)
        parts = [f'<a href="{trail.url}">{html.escape(trail.title)}</a>, {i + 1} of {len(trail.entries)}']
        if i > 0:
            prev = by_slug[trail.entries[i - 1]]
            parts.append(f'Previous: <a href="{prev.url}">{html.escape(prev.title)}</a>')
        if i < len(trail.entries) - 1:
            nxt = by_slug[trail.entries[i + 1]]
            parts.append(f'Next: <a href="{nxt.url}">{html.escape(nxt.title)}</a>')
        lines.append(f'<p class="trail-nav">{" • ".join(parts)}</p>')
    return lines


def entry_foot(e: Entry, book: Book) -> str:
    """Related entries and path navigation below an entry's text."""
    parts = []
    if (rel := related(e, book.entries)):
        parts.append('<h2 id="related-entries">Related</h2>')
        parts += [entry_row(other) for other in rel]
    parts += trail_nav(e, book.trails, {x.slug: x for x in book.entries})
    return "\n".join(parts)


def trail_body(trail: Trail, by_slug: dict[str, Entry]) -> str:
    """A reading path's page: its entries, numbered in order."""
    return "\n".join(
        f'<div class="entry"><p>{i}</p><p><a href="{by_slug[s].url}">{html.escape(by_slug[s].title)}</a></p>'
        f'<p class="kind">{type_label(by_slug[s].types)}</p></div>'
        for i, s in enumerate(trail.entries, start=1))

