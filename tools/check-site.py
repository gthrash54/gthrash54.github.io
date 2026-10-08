#!/usr/bin/env python3
"""Pre-commit checks: local links resolve, head tags present, one h1, JSON-LD parses, XML valid, banned words absent."""
import json, re, sys, subprocess, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
bad = 0
pages = sorted(ROOT.glob("*.html")) + sorted((ROOT / "writing").glob("*.html"))
for p in pages:
    s = p.read_text()
    for m in re.finditer(r'(?:href|src)="([^"#]+)(?:#[^"]*)?"', s):
        u = m.group(1)
        if u.startswith(("http", "mailto:", "data:", "tel:")): continue
        t = (ROOT / u.lstrip("/")) if u.startswith("/") else (p.parent / u)
        if not t.exists(): print(f"BROKEN {p.name}: {u}"); bad += 1
    if p.name == "404.html": continue
    for tag in ['<title>', 'name="description"', 'og:title', 'og:image" content="https://', 'rel="icon" href="/favicon.svg"', 'rel="canonical"']:
        if tag not in s: print(f"MISSING {p.name}: {tag}"); bad += 1
    if (n := s.count("<h1")) != 1: print(f"H1 x{n} {p.name}"); bad += 1
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', s, re.S):
        try: json.loads(m.group(1))
        except Exception as e: print(f"JSONLD {p.name}: {e}"); bad += 1
    for w in ("physician", "stealth", "pre-seed", "Tools I build", "hidden>", "direct AI"):
        if w in s: print(f"WORD {p.name}: {w!r}"); bad += 1
json.load(open(ROOT / "figures/figures.json"))
for x in ("sitemap.xml", "feed.xml"):
    if (ROOT / x).exists() and subprocess.run(["xmllint", "--noout", str(ROOT / x)]).returncode: bad += 1
print("OK" if not bad else f"{bad} problem(s)")
sys.exit(1 if bad else 0)
