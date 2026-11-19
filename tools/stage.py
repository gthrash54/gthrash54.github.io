#!/usr/bin/env python3
"""Stage one PhD Vault note as a commonplace draft, keeping only what is explicitly allowed. Never runs git.

A vault note keeps textbook-level content next to unpublished plans and lab results, so staging works
from an allow-list: everything not explicitly kept is dropped, and every drop is reported.

Kept:
    the opening definition (the first block under the title, when it is a blockquote), unquoted,
    as the lead paragraph
    the sections in KEEP_DEFAULT ("What is established"), any section named with --keep,
    or every section with --all
Always dropped, even with --all:
    the H1 title (the site prints its own) and the vault front matter
    the note's own "Sources" section (rebuilt below from the literature notes)
    blockquotes (except the opening definition), including Obsidian callouts and their continuations,
    %% comments %%,
    <!-- HTML comments -->, embeds ![[...]] and images, and navigation lines such as
    "- [[Topics Index]] · [[Home]]"
Rewritten:
    [[citekey]] -> [n], numbered by first appearance, with a numbered Sources list built from the
    literature notes' front matter; [[Note|alias]] -> alias; [[Note]] and [[Note#Heading]] -> Note
Flagged:
    every kept line matching IDENTIFIER_PATTERNS (case IDs, dates, phrases pointing at lab data)
    gets <!-- CHECK: reason --> at its end. This is a heuristic, not a guarantee: read every line
    before promoting.

Reads only the named note and the literature notes its kept text cites; the vault is never written.
Writes only drafts/commonplace/<slug>.md (git ignores drafts/). Then rewrite the draft in your own
words, delete each CHECK comment as you handle it, and run tools/promote.py <slug>.

Usage:
    python3 tools/stage.py "Aperiodic exponent"
    python3 tools/stage.py "11 - Topics/05 - Methods - signal processing/Aperiodic exponent.md"
Options:
    --topic SLUG      topic slug from commonplace/index.md (repeatable); default: the topic whose
                      `vault` folder holds the note
    --slug SLUG       file name for the entry; default: the title, slugified
    --keep "Heading"  also keep this section (repeatable)
    --all             keep every section (callouts, comments, embeds and nav lines still go)
    --force           overwrite an existing draft
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build import (BOOK, DRAFT_ENTRIES, ENTRIES, ROOT, BuildError, fmt_name,  # noqa: E402
                   load_config, parse_name, plain_meta, read_meta)
from commonplace import CHECK, as_list, code_mask, entry_problems, parse_config, slugify  # noqa: E402

KEEP_DEFAULT = ("What is established",)   # sections kept without --keep or --all
ALWAYS_DROPPED = ("Sources",)             # rebuilt from the literature notes instead
SKIP_DIRS = {".obsidian", ".trash", "99 - Archive"}
LITERATURE = "02 - Literature"            # vault folder of literature notes: <theme>/<citekey>.md
SUMMARY = f"{CHECK} one sentence for Home, search results and the feed."

Meta = dict[str, object]                  # front matter with every string reduced to plain text

# (pattern, reason) pairs. A kept line matching any of them gets a CHECK comment naming the match.
# A heuristic, not a guarantee: it catches the common shapes of identifiers and of sentences about
# unpublished lab work, nothing more.
IDENTIFIER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bu[hg][-_ ]?\d+\b", re.I), "looks like a lab case ID"),
    (re.compile(r"\b(?:case|subject|patient|participant)s?[\s#:_-]*(?:no\.?\s*)?\d+", re.I),
     "looks like a numbered case, subject or patient"),
    (re.compile(r"\b(?:MRN|DOB|date of birth)\b", re.I), "looks like a medical record number or birth date"),
    (re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"), "looks like a full date"),
    (re.compile(r"\d{6,}"), "is a run of six or more digits"),
    (re.compile(r"\b(?:this archive|our (?:data|cohort)\w*|in hand|staged|unpublished|Cheaha|UH3|"
                r"Walker(?:'s)? lab)\b", re.I), "points at unpublished lab data or plans"),
    (re.compile(r"\bBox\b"), "points at unpublished lab data or plans"),   # case-sensitive: "box plot" is fine
]

HEADING = re.compile(r"^\s*(#{1,6})(?:\s+(.*?))?(?:\s+#+)?\s*$")
SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")                   # a "Title" line underlined with === or ---
COMMENT_OPEN = re.compile(r"%%|<!--")
COMMENT_CLOSE = {"%%": "%%", "<!--": "-->"}
QUOTE_PREFIX = r"^\s*(?:(?:[-*+]|\d+[.)])\s+)*(?:>\s*)+"
CALLOUT = re.compile(QUOTE_PREFIX + r"\[!([^\]]+)\]")
QUOTED = re.compile(QUOTE_PREFIX)
BLOCKQUOTE = re.compile(r"^\s*(?:>\s?)+")
EMBED = re.compile(r"!\[\[[^\]]*\]\]")
IMAGE = re.compile(r"!\[(?:\\.|[^\]\\])*\](?:\([^)]*\)|\[[^\]]*\])?")
HTML_IMAGE = re.compile(r"<img\b(?:[^\"'<>]|\"[^\"]*\"|'[^']*')*>", re.I)
PRIVATE_IMAGE = re.compile("|".join(p.pattern for p in (EMBED, IMAGE, HTML_IMAGE)), re.I)
WIKILINK = re.compile(r"(?<!!)\[\[([^\[\]]+)\]\]")
INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)")
IMAGE_OR_CODE = re.compile(PRIVATE_IMAGE.pattern + "|" + INLINE_CODE.pattern, re.I)
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# What may sit between the links of a navigation line: spaces, punctuation, a middle dot, a bullet,
# en and em dashes, and arrows.
NAV_SEPARATORS = re.compile(r"[\s,;:|/>\-\u00b7\u2022\u2013\u2014\u2190\u2192]*")   # re reads \uXXXX
NAV_TARGET = re.compile(r"Home|.*\bIndex", re.I)
CITEKEY = re.compile(r"[a-z][a-z0-9_-]*\d{4}[a-z0-9_-]*")      # Better BibTeX style: donoghue2020parneu
MD_SPECIAL = re.compile(r"([\\`*_\[\]<>$^~])")


class StageError(Exception):
    """A problem that stops staging with a clear message."""


@dataclass(frozen=True)
class Section:
    """A heading and its own lines, stopping at any next heading. The lead has no title."""
    title: str | None
    lines: tuple[str, ...]
    level: int = 2


@dataclass(frozen=True)
class Staged:
    """The kept Markdown of a note and an account of what happened to the rest."""
    h1: str | None              # the note's title heading, dropped
    body: str                   # kept Markdown, links rewritten and identifiers flagged
    cited: tuple[str, ...]      # citekeys in citation order: [1] is cited[0]
    kept: tuple[str, ...]       # report lines
    dropped: tuple[str, ...]    # report lines
    flagged: int                # lines given an identifier CHECK


# ---------- Markdown structure (pure) ----------------------------------------------------------

def split_front_matter(text: str) -> tuple[str, str]:
    """('---\\nyaml\\n---\\nbody') -> ('yaml', 'body'); text without front matter -> ('', text)."""
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return "", text
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    raise StageError("the front matter opened by '---' on the first line is never closed")


def checked_code_mask(lines: list[str]) -> list[bool]:
    """Use promotion's code mask, rejecting an unclosed fence.

    An unclosed fence is an error: everything after it, headings included, would be read as code,
    so a private section could end up inside a kept one.
    """
    mask, unclosed = code_mask(lines)
    if unclosed:
        raise StageError("a code fence is never closed; close it in the vault note")
    return mask


def strip_comments(lines: list[str]) -> tuple[list[str], list[str]]:
    """Remove %% Obsidian comments %% and <!-- HTML comments -->, which may span lines.

    Markers inside fenced code are code, not comments. A comment that is never closed hides the rest
    of the note, as it does in Obsidian. A line left blank by a removed comment is dropped.
    Returns (lines, report).
    """
    out: list[str] = []
    count, closer = 0, ""
    code, _ = code_mask(lines)
    for i, line in enumerate(lines):
        if not closer and code[i]:
            out.append(line)
            continue
        was_hidden, before = bool(closer), count
        kept, rest = "", line
        while rest:
            if closer:
                end = rest.find(closer)
                if end < 0:
                    break
                rest, closer = rest[end + len(closer):], ""
            elif (m := COMMENT_OPEN.search(rest)):
                kept, rest, closer = kept + rest[:m.start()], rest[m.end():], COMMENT_CLOSE[m.group()]
                count += 1
            else:
                kept, rest = kept + rest, ""
        if not was_hidden and count == before:
            out.append(line)
        elif kept.strip():
            out.append(kept.rstrip())
        if (was_hidden or count != before) and not closer:
            # Fences inside a removed comment must not affect the following text.
            code[i:], _ = code_mask([kept.rstrip(), *lines[i + 1:]])
    report = [f"{count} comment(s) (%% or <!-- -->)"] if count else []
    if closer:
        report.append(f"everything after an unclosed {'%%' if closer == '%%' else '<!--'} comment")
    checked_code_mask(out)
    return out, report


def heading_at(lines: list[str], i: int, code: list[bool]) -> tuple[int, str, int]:
    """(level, text, lines used) for an ATX or setext heading; (0, '', 1) otherwise.

    Setext headings count too. Mistaking a line for a heading only adds a section boundary, and an
    unknown section is dropped, so erring this way is safe.
    """
    if code[i]:
        return 0, "", 1
    if (m := HEADING.match(lines[i])):
        return len(m.group(1)), (m.group(2) or "").strip(), 1
    nxt = i + 1
    if (lines[i].strip() and nxt < len(lines) and not code[nxt]
            and (underline := SETEXT.match(lines[nxt]))):
        return (1 if underline.group(1)[0] == "=" else 2), lines[i].strip(), 2
    return 0, "", 1


def split_sections(lines: list[str]) -> tuple[str | None, list[Section]]:
    """Split a note body at every heading, outside code.

    Returns (the H1 title or None, sections). The first section is the lead (title None), the text
    before any section. The first H1, when no section has started, is the note's title: it is
    removed and the text under it stays in the lead. Each subsection is a separate section.
    """
    code = checked_code_mask(lines)
    h1: str | None = None
    title: str | None = None
    current_level = 2
    current: list[str] = []
    sections: list[Section] = []
    i = 0
    while i < len(lines):
        level, text, used = heading_at(lines, i, code)
        if not level:
            current.append(lines[i])
        elif level == 1 and h1 is None and title is None:
            h1 = text
        else:
            sections.append(Section(title, tuple(current), current_level))
            title, current, current_level = text, [], level
        i += used
    sections.append(Section(title, tuple(current), current_level))
    return h1, sections


def heading_key(title: str) -> str:
    """Section names compare without case or extra spaces."""
    return " ".join(title.split()).casefold()


def count_text(lines: tuple[str, ...] | list[str]) -> str:
    """'3 lines': the non-blank lines, for the report."""
    n = sum(1 for line in lines if line.strip())
    return f"{n} line" if n == 1 else f"{n} lines"


def choose_sections(sections: list[Section], keep: list[str], keep_all: bool) -> tuple[list[Section], list[str]]:
    """Apply the allow-list to the sections after the lead. Returns (kept sections, report of drops).

    A --keep name that matches no section, or names an always-dropped one, is an error.
    """
    always = {heading_key(name) for name in ALWAYS_DROPPED}
    present = [s.title for s in sections if s.title is not None]
    if (refused := [k for k in keep if heading_key(k) in always]):
        raise StageError(f"--keep {refused[0]!r}: that section is always rebuilt from the literature notes")
    if (missing := [k for k in keep if heading_key(k) not in {heading_key(t) for t in present}]):
        raise StageError(f"--keep {missing[0]!r}: no such section; the note has: "
                         + ", ".join(repr(t) for t in present))
    wanted = {heading_key(name) for name in (*KEEP_DEFAULT, *keep)}
    kept, report = [], []
    for s in sections:
        key = heading_key(s.title or "")
        if key in always:
            report.append(f'section "{s.title}" ({count_text(s.lines)}; rebuilt from the literature notes)')
        elif keep_all or key in wanted:
            kept.append(s)
        else:
            report.append(f'section "{s.title}" ({count_text(s.lines)})')
    return kept, report


# ---------- private markup (pure) --------------------------------------------------------------

def link_parts(inner: str) -> tuple[str, str, str]:
    """The inside of a wikilink, 'Folder/Note#Heading|alias', -> ('Note', 'Heading', 'alias')."""
    target, _, alias = re.sub(r"\\\|", "|", inner).partition("|")   # \| is a pipe escaped inside a table
    note, _, heading = target.partition("#")
    return note.rsplit("/", 1)[-1].strip(), heading.strip(), alias.strip()


def is_nav_line(line: str) -> bool:
    """True for a line of wikilinks and separators only, such as '- [[Topics Index]] · [[Home]]'.

    A single link counts only when it points at Home or an index note, so a one-item list such as
    '- [[Beta bursts]]' in a kept section stays.
    """
    body = LIST_MARKER.sub("", line, count=1)
    links = WIKILINK.findall(body)
    if not links or not NAV_SEPARATORS.fullmatch(WIKILINK.sub("", body)):
        return False
    return len(links) > 1 or bool(NAV_TARGET.fullmatch(link_parts(links[0])[0]))


def blockquote_end(lines: list[str], start: int, code: list[bool]) -> int:
    """Index just past a quote and its marked or lazy continuation lines.

    Conservatively consume through the next blank line or heading outside code. A fenced block
    in the continuation is consumed whole, including any blank lines inside it.
    """
    end = start + 1
    while end < len(lines) and (code[end] or (lines[end].strip() and not heading_at(lines, end, code)[0])):
        if not code[end] and LIST_MARKER.match(lines[end]) and QUOTED.match(lines[end]):
            break                               # a new list item starts another quote block
        end += 1
    return end


def strip_images(text: str, where: str) -> tuple[str, list[str]]:
    """Remove Markdown images, embeds and HTML img tags, including multiline tags, outside code."""
    report: list[str] = []

    def clean(prose: str) -> str:
        counts: dict[int, int] = {}

        def remove(match: re.Match[str]) -> str:
            if match.group().startswith("`"):
                return match.group()            # code spans win when they start before an image
            line = prose.count("\n", 0, match.start())
            counts[line] = counts.get(line, 0) + 1
            return "\n" * match.group().count("\n")

        cleaned = IMAGE_OR_CODE.sub(remove, prose)
        report.extend(f"{count} embed(s) or image(s) in {where}" for count in counts.values())
        return cleaned

    cleaned = map_prose(text, clean, protect_inline=False)
    lines = [after.rstrip() if before != after else after
             for before, after in zip(text.split("\n"), cleaned.split("\n"))
             if after.strip() or not before.strip()]
    return "\n".join(lines), report


def strip_private(lines: list[str], where: str, preserve_quotes: bool = False) -> tuple[list[str], list[str]]:
    """Drop quotes, embeds, images and navigation lines from one part of a note, outside code.

    `where` names the part in the report. preserve_quotes defers ordinary lead quotes to
    opening_definition; callouts are always dropped. Returns (lines, report).
    """
    code = checked_code_mask(lines)
    out, report, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        if code[i]:
            out.append(line)
            i += 1
        elif (callout := CALLOUT.match(line)) or (not preserve_quotes and QUOTED.match(line)):
            end = blockquote_end(lines, i, code)
            kind = f"callout [!{callout.group(1)}]" if callout else "blockquote"
            report.append(f"{kind} in {where} ({end - i} lines)")
            i = end
        elif is_nav_line(line):
            report.append(f"navigation line in {where}")
            i += 1
        else:
            out.append(line)
            i += 1
    cleaned, drops = strip_images("\n".join(out), where)
    return cleaned.split("\n") if cleaned else [], report + drops


def opening_definition(lead: list[str], keep_all: bool) -> tuple[list[str], list[str]]:
    """The lead paragraph: the lead's first block, when it is a blockquote, with its markers removed.

    The rest of the lead is kept only with keep_all. Returns (lines, report of drops).
    """
    start = next((i for i, line in enumerate(lead) if line.strip()), len(lead))
    end = next((i for i in range(start, len(lead)) if not lead[i].strip()), len(lead))
    first, rest = lead[start:end], lead[end:]
    found = bool(first) and bool(BLOCKQUOTE.match(first[0]))
    lines = [BLOCKQUOTE.sub("", line) for line in first] if found else []
    unused = rest if found else lead[start:]
    if keep_all:
        return lines + ([""] if lines else []) + unused, []
    if not any(line.strip() for line in unused):
        return lines, []
    what = "the rest of the text" if found else "the text (no blockquote definition found)"
    return lines, [f"{what} before the first section ({count_text(unused)})"]


def tidy(lines: list[str]) -> list[str]:
    """Trim blank lines at both ends and collapse runs of blank lines outside code to one."""
    code = checked_code_mask(lines)
    out: list[str] = []
    for line, in_code in zip(lines, code):
        if not in_code and not line.strip() and (not out or not out[-1].strip()):
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


# ---------- links and identifiers (pure) -------------------------------------------------------

def map_prose(text: str, fn: Callable[[str], str], protect_inline: bool = True) -> str:
    """Apply fn outside fenced code and, by default, inline code, in order.

    Image removal handles inline code itself so backticks inside an image cannot hide that image.
    """
    lines = text.split("\n")
    code = checked_code_mask(lines)
    out, i = [], 0
    while i < len(lines):
        end = i + 1
        while end < len(lines) and code[end] == code[i]:
            end += 1
        block = "\n".join(lines[i:end])
        if code[i]:
            out.append(block)
        elif protect_inline:
            parts, start = [], 0
            for match in INLINE_CODE.finditer(block):
                parts.extend((fn(block[start:match.start()]), match.group()))
                start = match.end()
            parts.append(fn(block[start:]))
            out.append("".join(parts))
        else:
            out.append(fn(block))
        i = end
    return "\n".join(out)


def is_citekey(name: str, known: set[str]) -> bool:
    """A literature note's name, a key from the note's `sources:`, or anything shaped like a citekey."""
    return name in known or bool(CITEKEY.fullmatch(name))


def convert_links(text: str, known: set[str]) -> tuple[str, list[str]]:
    """Rewrite wikilinks outside code: citations become [n], numbered by first appearance; other
    links become their alias or note name. Returns (text, citekeys in citation order).
    """
    cited: list[str] = []

    def replace(m: re.Match) -> str:
        note, heading, alias = link_parts(m.group(1))
        if note and is_citekey(note, known):
            if note not in cited:
                cited.append(note)
            number = f"[{cited.index(note) + 1}]"
            return f"{alias} {number}" if alias else number
        return alias or note or heading

    return map_prose(text, lambda part: WIKILINK.sub(replace, part)), cited


def identifier_hits(line: str) -> list[str]:
    """'"uh3021" looks like a lab case ID' for each IDENTIFIER_PATTERNS match in a line, without repeats."""
    hits: list[str] = []
    for pattern, reason in IDENTIFIER_PATTERNS:
        for m in pattern.finditer(line):
            hit = f'"{m.group(0)}" {reason}'
            if hit not in hits:
                hits.append(hit)
    return hits


def flag_identifiers(text: str) -> tuple[str, int]:
    """Append <!-- CHECK: ... --> to every line with an identifier hit, at the end of the line so
    lists and paragraphs keep their shape. Returns (text, number of lines flagged).
    """
    out, flagged = [], 0
    for line in text.split("\n"):
        if (hits := identifier_hits(line)):
            line = f"{line} <!-- {CHECK} {'; '.join(hits)} -->"
            flagged += 1
        out.append(line)
    return "\n".join(out), flagged


def stage_body(body: str, known: set[str], keep: list[str] | None = None, keep_all: bool = False) -> Staged:
    """Apply the allow-list to a note body (front matter already removed) and rewrite what is kept.

    `known` holds the names that are citekeys: the literature notes and the note's `sources:`.
    """
    lines, dropped = strip_comments(body.replace("\r\n", "\n").split("\n"))
    h1, sections = split_sections(lines)
    if h1 is not None:
        dropped.insert(0, f'title heading "{h1}"')
    chosen, drops = choose_sections(sections[1:], keep or [], keep_all)
    dropped += drops

    lead, drops = strip_private(list(sections[0].lines), "the text before the first section", preserve_quotes=True)
    dropped += drops
    definition, drops = opening_definition(lead, keep_all)
    dropped += drops
    definition, drops = strip_private(definition, "the text before the first section")
    dropped += drops
    definition = tidy(definition)
    parts, kept = [], []
    if definition:
        parts.append("\n".join(definition))
        kept.append("all text before the first section" if keep_all else "opening definition")
    for s in chosen:
        section, drops = strip_private(list(s.lines), f'"{s.title}"')
        dropped += drops
        text = "\n".join(tidy(section))
        heading = f"{'#' * max(2, s.level)} {s.title}"
        heading, drops = strip_images(heading, f'heading "{s.title}"')
        dropped += drops
        parts.append(f"{heading}\n{text}" if text else heading)
        kept.append(f'section "{s.title}"')

    markdown, cited = convert_links("\n\n".join(parts), known)
    markdown, flagged = flag_identifiers(markdown)
    return Staged(h1, markdown, tuple(cited), tuple(kept), tuple(dropped), flagged)


# ---------- references (pure) ------------------------------------------------------------------

def md_escape(text: str) -> str:
    """Backslash the characters Markdown would read as markup, for text taken from front matter."""
    return MD_SPECIAL.sub(r"\\\1", text)


def md_url(url: str) -> str:
    """A URL safe inside a Markdown link: spaces, parentheses and angle brackets percent-encoded."""
    for char, code in ((" ", "%20"), ("(", "%28"), (")", "%29"), ("<", "%3C"), (">", "%3E")):
        url = url.replace(char, code)
    return url


def md_name(raw: str) -> str:
    """'Thomas Donoghue' -> 'Donoghue T', via build.fmt_name; the site owner in **bold**."""
    formatted = fmt_name(*parse_name(raw))
    text = md_escape(html.unescape(re.sub(r"</?strong>", "", formatted)))
    return f"**{text}**" if formatted.startswith("<strong>") else text


def format_authors(authors: list[str]) -> str:
    """Vancouver short form: one or two authors in full, more as 'Donoghue T, et al.'."""
    names = ", ".join(md_name(a) for a in authors[:1 if len(authors) > 2 else 2])
    text = names + (", et al." if len(authors) > 2 else "")
    return text if text.endswith(".") else text + "."


def reference_link(meta: Meta) -> str:
    """A [doi](...) link, else a PubMed, arXiv or plain URL link; '' when the note has none."""
    def field(key: str) -> str:
        return str(meta.get(key) or "").strip()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", field("doi"), flags=re.I)
    arxiv = re.sub(r"^(?:https?://arxiv\.org/abs/|arxiv:\s*)", "", field("arxiv"), flags=re.I)
    if doi:
        return f"[doi]({md_url('https://doi.org/' + doi)})"
    if field("pmid").isdigit():
        return f"[pubmed](https://pubmed.ncbi.nlm.nih.gov/{field('pmid')}/)"
    if arxiv:
        return f"[arxiv]({md_url('https://arxiv.org/abs/' + arxiv)})"
    if field("url").startswith(("https://", "http://")):
        return f"[link]({md_url(field('url'))})"
    return ""


def format_reference(key: str, meta: Meta | None) -> str:
    """One Sources item from a literature note's front matter; None means the note was not found.

    'Donoghue T, et al. Title. *Journal* (2020). [doi](https://doi.org/...)'. Missing fields and
    missing notes get their own CHECK comment.
    """
    if meta is None:
        return f"`{key}` <!-- {CHECK} no literature note for citekey {key}; write this reference by hand -->"
    parts = []
    authors = as_list(meta.get("authors"))
    title = str(meta.get("title") or "").strip()
    journal, year = str(meta.get("journal") or "").strip(), str(meta.get("year") or "").strip()
    if authors:
        parts.append(format_authors(authors))
    if title:
        parts.append(md_escape(title) + ("" if title[-1] in ".?!" else "."))
    source = " ".join(filter(None, [f"*{md_escape(journal)}*" if journal else "", f"({year})" if year else ""]))
    if source:
        parts.append(source + ".")
    if (link := reference_link(meta)):
        parts.append(link)
    missing = [name for name, value in (("authors", authors), ("title", title), ("journal", journal),
                                        ("year", year), ("DOI or link", link)) if not value]
    text = " ".join(parts) or f"`{key}`"
    if missing:
        text += f" <!-- {CHECK} the literature note for {key} has no {', '.join(missing)} -->"
    return text


def sources_section(cited: list[str], refs: dict[str, Meta | None]) -> str:
    """'## Sources' and a numbered list in citation order; '' when nothing is cited."""
    if not cited:
        return ""
    items = "\n".join(f"{n}. {format_reference(key, refs.get(key))}" for n, key in enumerate(cited, start=1))
    return (f"## Sources <!-- {CHECK} these references come from unverified vault notes; "
            f"confirm each against its DOI -->\n\n{items}")


# ---------- the draft (pure) -------------------------------------------------------------------

def entry_meta(title: str, topics: list[str], today: dt.date) -> Meta:
    """The new entry's front matter, with the summary left as a CHECK."""
    return {"title": title, "summary": SUMMARY, "type": "note", "topics": topics, "added": today.isoformat()}


def front_matter(meta: Meta) -> str:
    """YAML front matter; strings and lists written with json.dumps, which YAML reads as quoted values."""
    def quoted(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)
    return (f"---\ntitle: {quoted(meta['title'])}\nsummary: {quoted(meta['summary'])}\n"
            f"type: {meta['type']}\ntopics: {quoted(meta['topics'])}\nadded: {meta['added']}\n---\n")


def header_comment(source: str, today: dt.date, verified: object, warnings: list[str]) -> str:
    """The CHECK under the front matter: where the draft came from and what has to happen to it."""
    if verified is True or str(verified).lower() == "true":
        state = "The vault note is marked verified: true, which is not a check of this text."
    elif verified is False or str(verified).lower() == "false":
        state = "The vault note is marked verified: false."
    else:
        state = "The vault note has no verified field."
    extra = "".join(f" {w[0].upper()}{w[1:]}." for w in warnings)
    return (f'<!-- {CHECK} staged from the PhD Vault note "{source}" on {today.isoformat()}. {state}{extra} '
            "Check every claim against its source and rewrite it in your own words; "
            "delete each CHECK comment once it is handled. -->")


def assemble_document(meta: Meta, header: str, body: str, sources: str) -> str:
    """Front matter, the header CHECK, the kept text, then Sources."""
    parts = [header, body.strip(), sources]
    return front_matter(meta) + "\n\n".join(p for p in parts if p) + "\n"


def note_title(meta: Meta, h1: str | None, stem: str) -> str:
    """The entry title: the note's `topic:`, else its H1, else its file name."""
    return str(meta.get("topic") or "").strip() or (h1 or "").strip() or stem


def choose_topics(given: list[str], note: Path, topics: dict[str, str]) -> tuple[list[str], str]:
    """Topic slugs for the entry and where they came from.

    `topics` maps slug -> vault folder name. --topic wins; otherwise the nearest folder holding the
    note that a topic names. Unknown or missing topics are errors that list the slugs.
    """
    choices = ", ".join(topics)
    if given:
        if (unknown := [t for t in given if t not in topics]):
            raise StageError(f"unknown topic {unknown[0]!r}; topics in commonplace/index.md: {choices}")
        return list(dict.fromkeys(given)), "--topic"
    for folder in reversed(note.parent.parts):
        if (match := [slug for slug, vault in topics.items() if vault and vault == folder]):
            return match, f'vault folder "{folder}"'
    raise StageError(f"no topic in commonplace/index.md names the folder {note.parent.as_posix()!r}; "
                     f"choose one with --topic: {choices}")


# ---------- finding notes ----------------------------------------------------------------------

def vault_notes(vault: Path) -> list[Path]:
    """Every .md file in the vault, relative to it, outside SKIP_DIRS. Lists names; reads nothing."""
    found = []
    for folder, subfolders, files in os.walk(vault):
        subfolders[:] = sorted(d for d in subfolders if d not in SKIP_DIRS)
        found += [(Path(folder) / f).relative_to(vault) for f in sorted(files) if f.endswith(".md")]
    return found


def resolve_note(query: str, notes: list[Path]) -> Path:
    """The one note a name (file name without .md, any case) or a vault-relative path picks out.

    Zero or several matches is a StageError that lists the candidates.
    """
    if "/" in query or query.endswith(".md"):
        wanted = Path(query if query.endswith(".md") else query + ".md")
        if wanted in notes:
            return wanted
        raise StageError(f"no note at {query!r} (paths are relative to the vault; "
                         f"{', '.join(sorted(SKIP_DIRS))} are skipped)")
    matches = [p for p in notes if p.stem.casefold() == query.casefold()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise StageError(f"{len(matches)} notes are named {query!r}; give one as a vault-relative path:\n  "
                         + "\n  ".join(p.as_posix() for p in matches))
    near = [p for p in notes if query.casefold() in p.stem.casefold()][:10]
    raise StageError(f"no note named {query!r}" + (":\n  did you mean\n  " + "\n  ".join(p.as_posix() for p in near)
                                                   if near else ""))


def literature_index(vault: Path) -> dict[str, list[Path]]:
    """citekey -> literature notes, from 02 - Literature/<theme>/<citekey>.md. Lists names; reads nothing."""
    index: dict[str, list[Path]] = {}
    for path in sorted((vault / LITERATURE).glob("*/**/*.md")):
        index.setdefault(path.stem, []).append(path)
    return index


# ---------- input and output -------------------------------------------------------------------

def read_references(cited: tuple[str, ...], index: dict[str, list[Path]]) -> dict[str, Meta | None]:
    """Front matter of each cited literature note (None when there is none). Reads only those notes."""
    refs: dict[str, Meta | None] = {}
    for key in cited:
        paths = index.get(key, [])
        if len(paths) > 1:
            raise StageError(f"citekey {key} has {len(paths)} literature notes: " + ", ".join(map(str, paths)))
        refs[key] = plain_meta(read_meta(paths[0])) if paths else None
    return refs


def topic_folders() -> dict[str, str]:
    """slug -> vault folder for each topic in commonplace/index.md."""
    topics, _ = parse_config(plain_meta(read_meta(BOOK / "index.md")))
    return {t.slug: t.vault for t in topics}


def stage_report(source: str, target: Path, topics: list[str], how: str, staged: Staged,
           missing: list[str], warnings: list[str], checks: int) -> str:
    """What stage.py did, for the terminal."""
    rows = [f"Staged {source}", f"    -> {target.relative_to(ROOT)}", f"Topics: {', '.join(topics)} (from {how})",
            "Kept:"] + [f"  {k}" for k in staged.kept or ["nothing"]]
    rows += ["Dropped:", "  the vault front matter (the entry has its own)"] + [f"  {d}" for d in staged.dropped]
    rows.append(f"Citations: {len(staged.cited)}" + (f" ({', '.join(staged.cited)})" if staged.cited else ""))
    if missing:
        rows.append(f"  no literature note: {', '.join(missing)}")
    rows += [f"Warning: {w}" for w in warnings]
    rows.append(f"Lines flagged as possible identifiers or unpublished work: {staged.flagged}")
    rows.append(f"CHECK comments to resolve: {checks}")
    rows.append(f"Next: rewrite it in your own words, then python3 tools/promote.py {target.stem}")
    return "\n".join(rows)


def stage(args: argparse.Namespace, today: dt.date) -> str:
    """Find the note, stage it, write the draft; return the report."""
    vault = load_config().get("vault")
    if vault is None or not vault.is_dir():
        raise StageError(f"the vault {vault} is not a folder (set `vault` in site.json)")
    rel = resolve_note(args.note, vault_notes(vault))
    note = vault / rel
    meta = plain_meta(read_meta(note))
    folders = topic_folders()
    topics, how = choose_topics(args.topic or [], rel, folders)

    index = literature_index(vault)
    known = set(index) | set(as_list(meta.get("sources")))
    staged = stage_body(split_front_matter(note.read_text(encoding="utf-8"))[1], known, args.keep, args.all)

    title = note_title(meta, staged.h1, rel.stem)
    slug = args.slug or slugify(title)
    fields = entry_meta(title, topics, today)
    if not slug:
        raise StageError("the title gives no slug; choose one with --slug")
    if (problems := entry_problems(slug, fields, set(folders))):
        raise StageError(f"cannot make entry {slug!r}: {'; '.join(problems)}")
    target, published = DRAFT_ENTRIES / f"{slug}.md", ENTRIES / f"{slug}.md"
    if published.exists():
        raise StageError(f"{published.relative_to(ROOT)} is already published; choose another --slug")
    if target.exists() and not args.force:
        raise StageError(f"{target.relative_to(ROOT)} exists; use --force to replace it")

    refs = read_references(staged.cited, index)
    warnings = []
    if str(meta.get("type") or "") != "topic":
        warnings.append(f"the vault note's type is {meta.get('type')!r}, not 'topic'")
    if (hits := identifier_hits(title)):
        warnings.append(f"the title: {'; '.join(hits)}")
    header = header_comment(rel.as_posix(), today, meta.get("verified"), warnings)
    document = assemble_document(fields, header, staged.body, sources_section(list(staged.cited), refs))

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8")
    missing = [key for key, ref in refs.items() if ref is None]
    return stage_report(rel.as_posix(), target, topics, how, staged, missing, warnings, document.count(CHECK))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """The command line."""
    parser = argparse.ArgumentParser(description="Stage a PhD Vault note as a commonplace draft.")
    parser.add_argument("note", help="note name (file name without .md) or vault-relative path")
    parser.add_argument("--topic", action="append", help="topic slug from commonplace/index.md (repeatable)")
    parser.add_argument("--slug", help="file name for the entry (default: the title, slugified)")
    parser.add_argument("--keep", action="append", default=[], help="also keep this section (repeatable)")
    parser.add_argument("--all", action="store_true", help="keep every section")
    parser.add_argument("--force", action="store_true", help="replace an existing draft")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Stage one note and print the report."""
    try:
        print(stage(parse_args(argv), dt.date.today()))
    except (StageError, BuildError) as err:
        print(f"stage.py: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
