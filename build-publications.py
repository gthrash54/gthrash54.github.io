#!/usr/bin/env python3
# NOTE: when a paper publishes and appears in the AUTO block, remove it from the hand-maintained
# "Accepted" / "Submitted" lists in publications.html, or it will show twice.
"""Regenerate the "Published" list in publications.html from the Zotero bib.

Source: ~/Dropbox/CV/publications.bib, which Better BibTeX auto-exports from
the Zotero collection "thrash_publications" (the same file the LaTeX CV uses).
Only the block between the AUTO-PUBLISHED markers is rewritten; the in-press,
under-review and presentation lists stay hand-maintained.

Rules mirror CV_GWT.tex: drop "Correction to:" errata, newest first,
names as "Thrash GW", the CV owner in bold. Author lists longer than
MAX_AUTHORS are shortened to the first three, the CV owner, and "et al."

Run from anywhere:  ~/Documents/gthrash54.github.io/build-publications.py
"""
import html, re, sys
from pathlib import Path

BIB = Path.home() / "Dropbox/CV/publications.bib"
PAGE = Path(__file__).resolve().parent / "publications.html"
BEGIN, END = "<!-- BEGIN AUTO-PUBLISHED -->", "<!-- END AUTO-PUBLISHED -->"
OWNER = "Thrash"
MAX_AUTHORS = 15   # longer lists: first 3 + owner + et al.
LEAD_AUTHORS = 3

# ---------- minimal bib(la)tex parser ----------------------------------------
def parse_bib(text):
    entries, i = [], 0
    while True:
        m = re.compile(r"@(\w+)\s*\{", re.S).search(text, i)
        if not m:
            return entries
        i = m.end()
        key_end = text.index(",", i)
        entry = {"type": m.group(1).lower(), "key": text[i:key_end].strip()}
        i = key_end + 1
        while True:
            fm = re.compile(r"\s*(\w+)\s*=\s*", re.S).match(text, i)
            if not fm:
                i = text.index("}", i) + 1
                break
            name, i = fm.group(1).lower(), fm.end()
            if text[i] == "{":
                depth, j = 0, i
                while True:
                    c = text[j]
                    depth += (c == "{") - (c == "}")
                    j += 1
                    if depth == 0:
                        break
                value, i = text[i + 1:j - 1], j
            elif text[i] == '"':
                j = text.index('"', i + 1)
                value, i = text[i + 1:j], j + 1
            else:
                j = re.compile(r"[,}]").search(text, i).start()
                value, i = text[i:j].strip(), j
            entry[name] = value
            tail = re.compile(r"\s*(,)?\s*(\})?", re.S).match(text, i)
            i = tail.end()
            if tail.group(2):
                break
        entries.append(entry)

def strip_braces(s):
    return re.sub(r"[{}]", "", s).strip()

# ---------- names -------------------------------------------------------------
def initials(given):
    given = strip_braces(given).replace(".", " ")
    parts = [p for p in re.split(r"[\s\-]+", given) if p]
    return "".join(p[0].upper() for p in parts)

def parse_name(raw):
    raw = raw.strip()
    if "=" in raw and re.search(r"\b(family|given)=", raw):
        parts = dict(kv.split("=", 1) for kv in re.split(r",\s*", raw) if "=" in kv)
        parts = {k.strip(): strip_braces(v) for k, v in parts.items()}
        return parts.get("family", ""), parts.get("given", ""), parts.get("prefix", "")
    if "," in raw:
        fam, giv = (x.strip() for x in raw.split(",", 1))
        toks = fam.split()
        # lowercase particles before the family name are a prefix (von, de, do)
        pre = []
        while len(toks) > 1 and toks[0].islower():
            pre.append(toks.pop(0))
        return strip_braces(" ".join(toks)), strip_braces(giv), " ".join(pre)
    toks = strip_braces(raw).split()
    return toks[-1], " ".join(toks[:-1]), ""

def fmt_name(fam, giv, pre):
    text = html.escape((pre + " " if pre else "") + fam)
    if giv:
        text += " " + initials(giv)
    return f"<b>{text}</b>" if fam.split()[-1] == OWNER else text

def fmt_authors(field):
    names = [parse_name(n) for n in re.split(r"\s+and\s+", field.strip())]
    if len(names) <= MAX_AUTHORS:
        return ", ".join(fmt_name(*n) for n in names)
    out, skipped = [], False
    for idx, n in enumerate(names):
        if idx < LEAD_AUTHORS or n[0].split()[-1] == OWNER:
            if skipped:
                out.append("…")
                skipped = False
            out.append(fmt_name(*n))
        else:
            skipped = True
    if skipped:
        out.append("et al.")
    return ", ".join(out)

# ---------- entry -> <li> -----------------------------------------------------
def sort_key(e):
    d = e.get("date") or e.get("year", "")
    parts = (d.split("-") + ["00", "00"])[:3]
    return tuple(int(p) if p.isdigit() else 0 for p in parts)

def fmt_entry(e):
    title = html.escape(strip_braces(e.get("title", "")))
    if title and title[-1] not in ".?!":
        title += "."
    journal = html.escape(strip_braces(e.get("journaltitle") or e.get("journal", "")))
    year = (e.get("date") or e.get("year", ""))[:4]
    cite = year
    if e.get("volume"):
        cite += f";{strip_braces(e['volume'])}"
        if e.get("number"):
            cite += f"({strip_braces(e['number'])})"
    if e.get("pages"):
        cite += f":{strip_braces(e['pages']).replace('--', '-')}"
    ids = []
    if e.get("doi"):
        doi = strip_braces(e["doi"])
        ids.append(f'<a href="https://doi.org/{html.escape(doi)}">DOI</a>')
    if e.get("eprinttype", "").lower() == "pubmed" and e.get("eprint"):
        pmid = strip_braces(e["eprint"])
        ids.append(f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/">PMID {pmid}</a>')
    elif e.get("pmid"):
        pmid = strip_braces(e["pmid"])
        ids.append(f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/">PMID {pmid}</a>')
    ids_html = f' <span class="ids">{" ".join(ids)}</span>' if ids else ""
    authors = fmt_authors(e.get("author", ""))
    if not authors.endswith("."):
        authors += "."
    return (f'    <li>{authors} '
            f'<span class="title">{title}</span> <i>{journal}.</i> {cite}.{ids_html}</li>')

def main():
    entries = [e for e in parse_bib(BIB.read_text(encoding="utf-8"))
               if not re.match(r"^\s*\{?Correction\s+to:", e.get("title", ""), re.I)
               and OWNER.lower() in e.get("author", "").lower()]  # skip items misfiled into the collection
    entries.sort(key=sort_key, reverse=True)
    block = "\n".join([BEGIN,
                       f"  <!-- Generated by build-publications.py from {BIB}. Do not edit by hand. -->",
                       '  <ol class="pubs">', *(fmt_entry(e) for e in entries),
                       "  </ol>", f"  {END}"])
    page = PAGE.read_text(encoding="utf-8")
    pat = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not pat.search(page):
        sys.exit(f"Markers {BEGIN} / {END} not found in {PAGE}")
    new = pat.sub(lambda _: block, page, count=1)
    changed = new != page
    if changed:
        PAGE.write_text(new, encoding="utf-8")
    print(f"{len(entries)} publications from {BIB.name}; "
          f"{'publications.html updated' if changed else 'publications.html already current'}.")

if __name__ == "__main__":
    main()
