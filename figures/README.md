# Adding a figure to the Research page

1. Put the figure file in this folder. Two kinds work:
   - Interactive: an HTML file exported from Plotly (`fig.write_html("name.html", include_plotlyjs="cdn")`)
     or from any tool that makes a standalone HTML page.
   - Static: a PNG or SVG image.
2. Add an entry to `figures.json`:

   { "title": "Short title", "file": "name.html", "caption": "One or two sentences.", "height": 440 }

   `height` (pixels) only matters for HTML figures. Entries appear in the order listed.
3. Run `./update.sh` from the site folder to publish.

Never put patient-level data here. Aggregate, de-identified results only.
