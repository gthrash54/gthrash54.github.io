# garrettthrash.com

Garrett Thrash's site. Markdown sources rendered by pandoc and one Python script into plain HTML, hosted on GitHub Pages. The design follows the CV: EB Garamond, small-caps headings, a date column, black on white with a deep green accent, dark mode from the system setting.

## Working on the site

    ./preview.sh        # build, check, and serve at http://localhost:8000 (Ctrl+C to stop)
    ./build.sh          # build and check only

Neither script runs git. When the preview looks right:

    git status                    # see what changed
    git diff                      # read it
    git add -A
    git commit                    # your message
    git push

GitHub Pages publishes `main` about a minute after a push.

## Files

| Path | What it is |
| --- | --- |
| `pages/*.md` | Page sources. `home.md` becomes `index.html`; `research.md` becomes `research/index.html`, and so on |
| `pages/projects/*.md` | One page per project, at `/projects/<name>/` |
| `writing/posts/*.md` | Essays; nothing is published until a post drops `draft: true` |
| `templates/base.html` | The one header, navigation and footer every page shares |
| `style.css` | All styling: light, dark, print |
| `build.py` | Renders everything; its docstring lists the front matter and tokens pages can use |
| `build.sh`, `preview.sh` | Tests, build, site check; preview also serves the site locally |
| `site.json` | Where the bibliography and CV PDF live outside the repo |
| `tests/` | Unit tests for `build.py` and the checker (`python3 -m unittest discover -s tests`) |
| `tools/check-site.py` | Broken links and anchors, head tags, banned words, British spellings, em dashes |
| `tools/og-card.html`, `tools/make-og.sh` | Source and renderer for `og.png`, the link-preview image |
| `build-manifest.txt` | Files the last build generated, so stale ones get removed |

Generated files (`index.html`, `*/index.html`, `sitemap.xml`, the three redirect pages `research.html`, `publications.html`, `talks.html`) are committed because Pages serves the repository as it is. Edit the sources, not these.

## House rules

- **Status wording** matches the CV: "M.D. Candidate (c/o 2027) • Incoming Ph.D. Student, Neuroengineering (2027)". Not physician, engineer, clinician or founder. Revisit at formal enrollment in May 2027.
- **AI-built software is labeled** "AI-built, directed by me".
- **Nothing interactive goes up unless Garrett designed it.** Planned spots say "Coming soon."
- **No patient-level data**, in figures or anywhere else.
- American English; no em dashes. The checker enforces both.

## Common edits

**A paper publishes.** Zotero's Better BibTeX export updates `~/Dropbox/CV/publications.bib`; the next build lists it. Remove it from the In Press or Under Review list in `pages/publications.md`, and add its key to a theme on `pages/research.md` (keys look like `<!-- pubs:keys thrash2026neures ... -->`).

**The Now section.** Edit the bullets in `pages/about.md` and set `now: YYYY-MM` in its front matter. The build warns when it is more than 90 days old.

**A project.** Copy `pages/projects/ai-evidence-screening.md`, edit it, and add an entry under Tools in `pages/research.md`.

**An essay.** Write `writing/posts/<slug>.md` with `title`, `date` (YYYY-MM-DD) and `summary` in the front matter; `draft: true` keeps it unpublished. Images go in `writing/images/` and are referenced as `/writing/images/name.jpg`. For a piece published elsewhere, add `external: <url>` and `outlet: <name>` instead of a body. Writing joins the navigation at three published posts.

**A CV-style entry** in any page:

    ::: entry
    2024 – present

    **Title**\
    Place\
    *Note*

    - Bullet
    :::

The first paragraph is the date column; everything after it sits on the right.
