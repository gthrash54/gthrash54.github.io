# garrettthrash.com

Garrett Thrash's personal site. Plain HTML + CSS, hosted on GitHub Pages, no framework. Two small Python builders keep generated parts current.

| File | What it is |
| --- | --- |
| `index.html` | Landing page: tagline, status line, buttons, the dated "Now" strip, footer links |
| `research.html` | Research & Projects: Walker Lab, interactive figures, tools built with AI agents, experience |
| `publications.html` | Peer-reviewed list (generated), in-press, under review, posters |
| `talks.html` | Talks & Teaching: invited lectures, oral presentations, teaching, speaker bios and headshot |
| `cv.pdf` | Copy of `~/Dropbox/CV/CV_GWT.pdf` (refreshed by `update.sh`) |
| `figures/` | Interactive figures for the Research page; see `figures/README.md` |
| `images/` | Screenshots used on pages |
| `style.css` | All styling (dark, light, print) |
| `build-publications.py` | Rewrites the Published block from the Zotero bib export |
| `tools/make-og.py` | One-off generator for `og.png`, the share-card image (needs font files; see its docstring) |
| `sitemap.xml`, `robots.txt`, `404.html`, `favicon.*`, `apple-touch-icon.png` | Plumbing |

## Publishing changes

From this folder:

    ./update.sh

It regenerates the Published list, copies the latest CV PDF from Dropbox, commits, and pushes. The site updates in about a minute. It warns if the landing page's "Now" strip is more than 90 days old; edit the three bullets and the month in `index.html` when that happens.

## House rules

- **Status wording.** "MD Candidate (Class of 2027) · Incoming PhD Student, Neuroengineering (2027)". Not physician, engineer, clinician, or founder.
- **AI-built software is labelled.** AnalyzeLFPs, the curriculum, and the pipelines were coded by AI agents from Garrett's specifications. Every mention says so ("designed by me, coded by AI agents" / "AI-built, directed by me").
- **Nothing about the device concept.** Only the one "Now" bullet on the landing page. The Ventures page draft lives outside this repo at `~/Dropbox/Start-up/Plans/site-ventures.html` and is published only after HIIE sign-off. Keep commit messages free of device details too.
- **No patient-level data**, in figures or anywhere else.
- **When a paper publishes**, remove it from the hand-maintained in-press/under-review lists; the bib export will add it to Published.

## Adding things

**A talk video.** Upload to YouTube (unlisted is fine). In `talks.html`, add a `<section id="video">` at the top of `<main>` with one block per video:

    <h2>Video</h2>
    <div class="video-grid">
      <div>
        <div class="video"><iframe src="https://www.youtube-nocookie.com/embed/VIDEO_ID" title="TALK TITLE" loading="lazy" allow="accelerometer; encrypted-media; picture-in-picture" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe></div>
        <h3>TALK TITLE</h3>
        <p class="muted">Venue, Month YYYY · <a href="slides/FILE.pdf">Slides (PDF)</a></p>
        <p>One-paragraph abstract.</p>
      </div>
    </div>

Then rename the page and nav entries to "Talks & Media".

**A figure.** See `figures/README.md`.

**A screenshot.** Put a JPG/PNG in `images/`, reference it with `<img class="shot" ...>` inside a card.

**Writing.** Not built yet. Planned: Markdown posts in `writing/posts/`, rendered by `build-writing.py` with pandoc into `writing/`, plus `feed.xml`. It gets built together with the first post.
