#!/usr/bin/env python3
"""Publish a staged commonplace draft: move drafts/commonplace/<slug>.md to commonplace/entries/. Never runs git.

The text moves unchanged. Nothing moves while the draft has a problem the build would reject:
front matter commonplace.entry_problems refuses, a CHECK comment or [[wikilink]] left from staging
(commonplace.text_problems), or a slug that is already published. Every problem is listed.

Usage: python3 tools/promote.py <slug>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build import BOOK, DRAFT_ENTRIES, ENTRIES, ROOT, BuildError, plain_meta, read_meta  # noqa: E402
from commonplace import entry_problems, parse_config, slugify, text_problems  # noqa: E402

Meta = dict[str, object]


def promote_problems(slug: str, meta: Meta, text: str, topic_slugs: set[str], published: set[str]) -> list[str]:
    """Everything that stops a draft from being published; empty when it is ready.

    `text` is the whole file, front matter included, so a CHECK left in the summary counts.
    `published` holds the slugs already in commonplace/entries/.
    """
    problems = entry_problems(slug, meta, topic_slugs) + text_problems(text)
    if slug in published:
        problems.append(f"already published: commonplace/entries/{slug}.md exists")
    return problems


def next_steps(slug: str) -> str:
    """What to do after the move. This script never runs git."""
    return (f"Moved drafts/commonplace/{slug}.md to commonplace/entries/{slug}.md, text unchanged.\n"
            "Next:\n"
            f"  1. ./preview.sh   check the entry at http://localhost:8000/commonplace/{slug}/\n"
            "  2. ./build.sh     build the site in place\n"
            "  3. Review with git status and git diff, then commit it yourself.")


def main(argv: list[str] | None = None) -> int:
    """Check the draft; move it only when nothing is wrong."""
    parser = argparse.ArgumentParser(description="Publish a staged commonplace draft.")
    parser.add_argument("slug", help="the draft's file name without .md")
    slug = parser.parse_args(argv).slug
    if not slug or slug != slugify(slug):
        print(f"promote.py: {slug!r} is not a slug (lowercase words joined by hyphens)", file=sys.stderr)
        return 1
    draft, target = DRAFT_ENTRIES / f"{slug}.md", ENTRIES / f"{slug}.md"
    if not draft.is_file():
        drafts = sorted(p.stem for p in DRAFT_ENTRIES.glob("*.md"))
        print(f"promote.py: no draft at {draft.relative_to(ROOT)}"
              + (f"; drafts: {', '.join(drafts)}" if drafts else ""), file=sys.stderr)
        return 1
    try:
        meta = plain_meta(read_meta(draft))
        topics, _ = parse_config(plain_meta(read_meta(BOOK / "index.md")))
    except BuildError as err:
        print(f"promote.py: {err}", file=sys.stderr)
        return 1
    published = {p.stem for p in ENTRIES.glob("*.md")}
    problems = promote_problems(slug, meta, draft.read_text(encoding="utf-8"), {t.slug for t in topics}, published)
    if problems:
        print(f"promote.py: {draft.relative_to(ROOT)} is not ready; nothing was moved:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    draft.rename(target)
    print(next_steps(slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
