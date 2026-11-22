# garrettthrash.com

Garrett Thrash's site. Markdown sources rendered by pandoc and one Python script into plain HTML, hosted on GitHub Pages. The design follows the CV: EB Garamond, small-caps headings, a date column, black on white with a deep green accent, dark mode from the system setting. Home has its own layout (the name beside Cajal's Purkinje cells, a closed-loop DBS strip, then stacked lists), and on wide screens every page carries Cajal's cortical column in the right margin.

## Working on the site

    ./preview.sh        # build and check, then build a preview with drafts and serve it at
                        # http://localhost:8000 (Ctrl+C to stop)
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
| `writing/posts/*.md` | Published essays and pieces published elsewhere. See Writing below |
| `commonplace/` | The commonplace book: `index.md` (topics and reading paths), `entries/*.md`, `images/`. See Commonplace below |
| `img/` | Santiago Ramón y Cajal's drawings (public domain), traced to SVG: the Purkinje cells on Home and the cortical column in the margin |
| `drafts/` | Ignored by git: unpublished essays in `drafts/writing/`, staged commonplace entries in `drafts/commonplace/`, the preview build in `drafts/_site/` |
| `templates/base.html` | The one header, navigation, margin drawing and footer every page shares |
| `style.css` | All styling: light, dark, print. Home's own rules sit under `.home` (from `class: home` in its front matter) |
| `build.py` | Renders everything; its docstring lists the front matter and tokens pages can use |
| `commonplace.py` | The commonplace book's checks and HTML; its docstring lists an entry's front matter |
| `build.sh`, `preview.sh` | Tests, build, site check; preview also builds drafts into `drafts/_site` and serves it |
| `site.json` | Where the bibliography and CV PDF live outside the repo |
| `tests/` | Unit tests for `build.py`, `commonplace.py` and the tools (`python3 -m unittest discover -s tests`) |
| `tools/check-site.py` | Broken links and anchors, head tags, banned words, British spellings, em dashes, CHECK comments |
| `tools/serve.py` | Serves `drafts/_site` over the repository on 127.0.0.1, for the preview |
| `tools/og-card.html`, `tools/make-og.sh` | Source and renderer for `og.png`, the link-preview image |
| `build-manifest.txt` | Files the last build generated, so stale ones get removed |

Generated files (`index.html`, `*/index.html`, `sitemap.xml`, the three redirect pages `research.html`, `publications.html`, `talks.html`) are committed because Pages serves the repository as it is. Edit the sources, not these.

## House rules

- **Status wording** matches the CV: "MD Candidate (Class of 2027) • Incoming PhD Student, Neuroengineering (2027)". Not physician, engineer, clinician or founder. Revisit at formal enrollment in May 2027.
- **Software AI built end to end is labeled** "AI-built, directed by me". Code Garrett wrote with AI assistance (clean_dbs, preprocess_dbs) gets no label: some AI assistance is assumed in all coding now.
- **Nothing interactive goes up unless Garrett designed it.** Planned spots say "Coming soon."
- **No patient-level data**, in figures or anywhere else.
- American English; no em dashes. The checker enforces both.

## Common edits

**A paper publishes.** Zotero's Better BibTeX export updates `~/Dropbox/CV/publications.bib`; the next build lists it. Remove it from the In Press or Under Review list in `pages/publications.md`, and add its key to a theme on `pages/research.md` (keys look like `<!-- pubs:keys thrash2026neures ... -->`).

**The Now section.** Edit the bullets in `pages/about.md` and set `now: YYYY-MM` in its front matter. The build warns when it is more than 90 days old.

**A project.** Copy `pages/projects/ai-evidence-screening.md`, edit it, and add an entry under Tools in `pages/research.md`.

**Home.** `pages/home.md` holds the hero and the closed-loop strip as raw HTML, then Markdown. Its Research list is a `:::: cards` block of `::: card` items (first paragraph the dates, then the linked title, then the place). Three tokens fill the rest from other sources: `<!-- pubs:compact key ... -->` (Selected Publications, from the bibliography), `<!-- writing:recent -->` and `<!-- commonplace:recent -->` (each its heading and up to three newest items, or "Coming soon.").

**A CV-style entry** in any page:

    ::: entry
    2024 – present

    **Title**\
    Place\
    *Note*

    - Bullet
    :::

The first paragraph is the date column; everything after it sits on the right.

## Writing

`/writing/` is always built and always in the navigation. It has two sections, **Essays** (posts hosted here) and **Published Elsewhere** (posts that link out), each newest first, or "Coming soon." while empty. The feed (`/feed.xml`) and its link in every page's head appear once anything is published, and cover both kinds.

**An essay hosted here.** Write `writing/posts/<slug>.md`; the file name is the address (`/writing/<slug>/`).

    ---
    title: Why a medical student is doing a neuroengineering PhD
    date: 2027-01-12
    summary: One sentence, shown on /writing/, on Home and in the feed.
    updated: 2027-02-03        # optional; shown as "updated February 3, 2027"
    draft: true                # optional; drafts show only in the preview
    ---

    The text, in Markdown. Use ## for headings.

The page shows the title, then "January 12, 2027 • 4 min read" (words / 230, rounded up), the text, and Previous and Next links to the neighboring essays by date. Images go in `writing/images/` and are referenced as `/writing/images/name.jpg`. Write it in `drafts/writing/<slug>.md` while it is unfinished: git ignores that folder, and the repository and every file in it are public, so a draft in `writing/posts/` can be read even when it is not built. `./preview.sh` shows drafts. To publish, move the file to `writing/posts/` and delete `draft: true` if you used it.

**A piece published elsewhere.** The same front matter plus `external: <url>` and `outlet: <name>` (both are required together), and no body. It is listed under Published Elsewhere, links to the outlet, and has no page here.

The build stops on a date that is not YYYY-MM-DD, an `updated` earlier than `date`, or an `external` without an `outlet` (or the reverse), and lists every problem at once.

## Commonplace

Notes, derivations, code and readings at `/commonplace/`, one Markdown file per entry; the file name is the address (`commonplace/entries/beta-bursts.md` is `/commonplace/beta-bursts/`). `/commonplace/` and one page per topic (`/commonplace/topics/<topic>/`) are always built and always in the navigation; a topic with no entries says "Coming soon.". `/commonplace/` lists every topic with its entry count, then **Recent** (the five newest entries, once there are any) and **Paths** (once a path exists). Entry pages, path pages and the feed (`/commonplace/feed.xml`) are built only for entries that exist.

**Adding an entry.**

1. **Stage** a vault note: `python3 tools/stage.py "<vault note>"` writes a draft to `drafts/commonplace/<slug>.md`. Staging leaves `<!-- CHECK: reason -->` comments wherever something needs your judgment.
2. **Rewrite** the draft in your own words. Settle each CHECK comment and delete it, and replace any `[[wikilinks]]` with ordinary links or citations.
3. **Preview** with `./preview.sh`. Drafts show, marked "Draft". Leftover CHECK comments and wikilinks are only warnings here.
4. **Promote** it: `python3 tools/promote.py <slug>` publishes the draft to `commonplace/entries/<slug>.md`. It refuses an entry that still has a CHECK comment or a wikilink.
5. **Build** with `./build.sh`, then review and commit as usual. A published entry with a CHECK comment or a wikilink stops the build.

**Front matter** of an entry:

    ---
    title: Band power and the aperiodic exponent
    summary: One sentence, shown on Home and in the feed.
    type: derivation           # note, derivation, code or reading; or a list: [derivation, code]
    topics: [signal-processing]
    added: 2027-01-12
    updated: 2027-02-03        # optional
    ---

Math in `$...$` or `$$...$$` becomes MathML, which browsers show without JavaScript. Images go in `commonplace/images/` and are referenced as `/commonplace/images/name.png`. Publication tokens work as on any page.

An entry page's breadcrumb links to each of its topic pages; below the text come up to three related entries (most shared topics first) and, for an entry on a reading path, links to the previous and next entry on it. The file names `entries`, `images`, `paths` and `topics` are reserved.

**Adding a topic.** Topics live in the front matter of `commonplace/index.md`, in the order they are listed on `/commonplace/`:

    topics:
      - slug: signal-processing          # what entries list under `topics:`; its page is /commonplace/topics/signal-processing/
        title: Signal Processing
        vault: "05 - Methods - signal processing"   # notes staged from this PhD Vault folder default to this topic

A new topic gets its page, saying "Coming soon.", on the next build.

**Adding a reading path.** A path is a short list of entries meant to be read in order, also in `commonplace/index.md`:

    paths:
      - slug: reading-a-power-spectrum
        title: Reading a Power Spectrum
        entries: [aperiodic-exponent, beta-bursts]

Every entry it lists must exist, once. The path gets a page at `/commonplace/paths/<slug>/`, is listed under Paths on `/commonplace/`, and each of its entries links to the previous and next one. Any text below the front matter of `commonplace/index.md` becomes the introduction on `/commonplace/`.
