# garrettthrash.com

Garrett Thrash's personal site. Plain HTML + CSS, hosted on GitHub Pages, no build step.

| File | What it is |
| --- | --- |
| `index.html` | Landing page with the buttons |
| `research.html` | Research & Projects: Walker Lab, interactive figures, tools, experience |
| `publications.html` | Publications and presentations |
| `cv.pdf` | Copy of `~/Dropbox/CV/CV_GWT.pdf` (refreshed by `update.sh`) |
| `figures/` | Interactive figures for the Research page; see `figures/README.md` |
| `style.css` | All styling (light, dark, print) |

## Publishing changes

From this folder:

    ./update.sh

It copies the latest CV PDF from Dropbox, commits, and pushes. The site updates in about a minute.
