"""Tests for build.py, tools/check-site.py and tools/serve.py.

Most tests cover pure functions. SiteBuildTests and ReadBookTests run real pandoc on temporary files.

Run from the repository root:  python3 -m unittest discover -s tests
"""
import contextlib
import datetime as dt
import importlib.util
import io
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402


def load_tool(name: str, filename: str):
    """Import a script from tools/ (its file name may have a hyphen, so plain import can't)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_site = load_tool("check_site", "check-site.py")
serve = load_tool("serve", "serve.py")

BIB = r"""
@article{thrash2026demo,
  title = {Therapeutic {{Deep Brain Stimulation}} for Restless Legs},
  author = {Thrash, Garrett W. and Wang, Emily and family=Campo, given=Rocio Vazquez, prefix=do, useprefix=true},
  date = {2026-03},
  journaltitle = {Sleep and Breathing},
  volume = {30},
  number = {1},
  pages = {28--35},
  doi = {10.1007/x},
  eprinttype = {pubmed},
  eprint = {41806217}
}
@article{other2025correction,
  title = {Correction to: Something},
  author = {Thrash, Garrett W.},
  date = {2025-12}
}
@online{misfiled2025,
  title = {Not His Paper},
  author = {Someone, Else},
  date = {2025-01}
}
"""


class BibTests(unittest.TestCase):
    def setUp(self):
        self.pubs = build.select_publications(build.parse_bib(BIB))

    def test_selection_drops_errata_and_misfiled(self):
        self.assertEqual(list(self.pubs), ["thrash2026demo"])

    def test_fields_parsed(self):
        e = self.pubs["thrash2026demo"]
        self.assertEqual(e["volume"], "30")
        self.assertEqual(build.pub_date(e), (2026, 3, 0))

    def test_reference_format(self):
        html = build.fmt_pub(self.pubs["thrash2026demo"])
        self.assertIn("<p>2026</p>", html)
        self.assertIn("<strong>Thrash GW</strong>, Wang E, do Campo RV.", html)
        self.assertIn("Therapeutic Deep Brain Stimulation for Restless Legs.", html)
        self.assertIn("<em>Sleep and Breathing</em> 30(1):28–35.", html)
        self.assertIn("https://doi.org/10.1007/x", html)
        self.assertIn("https://pubmed.ncbi.nlm.nih.gov/41806217/", html)

    def test_long_author_lists_are_shortened(self):
        names = " and ".join(f"Author{i}, A" for i in range(20)) + " and Thrash, Garrett W."
        out = build.fmt_authors(names)
        self.assertTrue(out.startswith("Author0 A, Author1 A, Author2 A, …, <strong>Thrash GW</strong>"))


class CompactTests(unittest.TestCase):
    """<!-- pubs:compact ... -->: journal and year, the linked title, the first author."""

    def setUp(self):
        self.pubs = build.select_publications(build.parse_bib(BIB))

    def test_compact_format(self):
        self.assertEqual(
            build.fmt_compact(self.pubs["thrash2026demo"]),
            '<div class="card"><p>Sleep and Breathing • 2026</p>'
            '<p><a href="https://doi.org/10.1007/x">Therapeutic Deep Brain Stimulation for Restless Legs</a></p>'
            '<p><strong>Thrash GW</strong>, et al.</p></div>')

    def test_pubmed_when_there_is_no_doi_and_no_link_without_either(self):
        paper = {**self.pubs["thrash2026demo"]}
        del paper["doi"]
        self.assertIn('<a href="https://pubmed.ncbi.nlm.nih.gov/41806217/">', build.fmt_compact(paper))
        del paper["eprint"]
        self.assertIn("<p>Therapeutic Deep Brain Stimulation for Restless Legs</p>", build.fmt_compact(paper))

    def test_short_author_line(self):
        self.assertEqual(build.short_authors("Thrash, Garrett W."), "<strong>Thrash GW</strong>")
        self.assertEqual(build.short_authors("Sun, Yi and Thrash, Garrett W."), "Sun Y, et al.")
        self.assertEqual(build.short_authors(""), "")

    def test_missing_journal_or_year_fails(self):
        with self.assertRaises(build.BuildError):
            build.fmt_compact({"key": "k", "title": "T", "author": "Thrash, G", "date": "2026"})
        with self.assertRaises(build.BuildError):
            build.fmt_compact({"key": "k", "title": "T", "author": "Thrash, G", "journaltitle": "J"})

    def test_token_lists_newest_first_in_one_stacked_list(self):
        pubs = {**self.pubs, "old2020": {"type": "article", "key": "old2020", "title": "Older",
                                         "author": "Thrash, Garrett W.", "date": "2020", "journaltitle": "Old J"}}
        out = build.expand_tokens("<!-- pubs:compact old2020 thrash2026demo -->", pubs, {}, "test")
        self.assertTrue(out.startswith('<div class="cards">\n<div class="card"><p>Sleep and Breathing • 2026</p>'))
        self.assertLess(out.index("Sleep and Breathing"), out.index("Old J • 2020"))
        self.assertTrue(out.endswith("</div>\n</div>"))

    def test_token_fails_on_unknown_or_missing_keys(self):
        for token in ("<!-- pubs:compact nope -->", "<!-- pubs:compact -->", "<!-- pubs:compactx -->"):
            with self.subTest(token=token), self.assertRaises(build.BuildError):
                build.expand_tokens(token, self.pubs, {}, "test")


class BibEdgeCaseTests(unittest.TestCase):
    def test_pages_without_volume_are_kept(self):
        self.assertEqual(build.fmt_source({"journaltitle": "Stereotact Funct Neurosurg", "pages": "1--19"}),
                         "<em>Stereotact Funct Neurosurg</em>, 1–19")

    def test_tex_escapes_decode_and_unknown_commands_fail(self):
        self.assertEqual(build.plain(r"Mergers \& {Acquisitions}"), "Mergers & Acquisitions")
        with self.assertRaises(build.BuildError):
            build.plain(r"\emph{Drosophila}")

    def test_unsupported_bib_syntax_fails(self):
        with self.assertRaises(build.BuildError):
            build.parse_bib("@article{k, author = {A, B}, title = {A} # {B}}")
        with self.assertRaises(build.BuildError):
            build.parse_bib("@article(k, title = {A})")

    def test_name_forms(self):
        self.assertEqual(build.parse_name("Thrash, Jr., Garrett W."), ("Thrash", "Garrett W.", "", "Jr."))
        self.assertEqual(build.parse_name("Ludwig van Beethoven"), ("Beethoven", "Ludwig", "van", ""))
        self.assertEqual(build.parse_name("{World Health Organization}"), ("World Health Organization", "", "", ""))
        self.assertEqual(build.split_authors("{Smith and Sons} and Thrash, G"), ["{Smith and Sons}", "Thrash, G"])

    def test_only_owner_articles_are_peer_reviewed(self):
        bib = ("@online{pre, title = {Preprint}, author = {Thrash, Garrett W.}, date = {2026}}\n"
               "@article{near, title = {Other}, author = {Thrasher, Bob}, date = {2026}}\n"
               "@article{his, title = {His}, author = {Thrash, Garrett W.}, date = {2026}}\n")
        self.assertEqual(list(build.select_publications(build.parse_bib(bib))), ["his"])


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.pubs = build.select_publications(build.parse_bib(BIB))

    def test_keys_and_counts_expand(self):
        body = "<!-- pubs:keys thrash2026demo -->\n<p>{{pub_count}} papers</p>"
        out = build.expand_tokens(body, self.pubs, {"pub_count": "1"}, "test")
        self.assertIn('class="entry ref"', out)
        self.assertIn("<p>1 papers</p>", out)

    def test_unknown_key_fails_loudly(self):
        with self.assertRaises(build.BuildError):
            build.expand_tokens("<!-- pubs:keys nope -->", self.pubs, {}, "test")

    def test_leftover_token_fails_loudly(self):
        with self.assertRaises(build.BuildError):
            build.expand_tokens("{{typo}}", self.pubs, {}, "test")

    def test_template_requires_every_field(self):
        with self.assertRaises(build.BuildError):
            build.fill_template("{{a}} {{b}}", {"a": "x"})

    def test_inserted_values_are_not_reread_as_tokens(self):
        self.assertEqual(build.fill_template("{{a}}|{{b}}", {"a": "{{b}}", "b": "B"}), "{{b}}|B")

    def test_two_sources_for_one_file_fail(self):
        outputs = {"writing/index.html": "page"}
        with self.assertRaises(build.BuildError):
            build.merge(outputs, {"writing/index.html": "posts"})

    def test_section_tokens_expand(self):
        body = "<p>x</p>\n<!-- writing:recent -->\n\n<!-- commonplace:recent -->"
        sections = {"writing": "<h2>W</h2>", "commonplace": "<h2>C</h2>"}
        self.assertEqual(build.expand_tokens(body, self.pubs, {}, "test", sections),
                         "<p>x</p>\n<h2>W</h2>\n\n<h2>C</h2>")

    def test_section_token_without_a_section_fails(self):
        with self.assertRaises(build.BuildError):
            build.expand_tokens("<!-- writing:recent -->", self.pubs, {}, "writing/posts/x.md")

    def test_malformed_section_tokens_fail(self):
        for token in ("<!-- commonplace:latest -->", "<!-- writing:newest -->"):
            with self.subTest(token=token), self.assertRaises(build.BuildError):
                build.expand_tokens(token, self.pubs, {}, "test", {"writing": "", "commonplace": ""})


class PageTests(unittest.TestCase):
    def test_out_paths(self):
        self.assertEqual(build.out_path("home"), ("index.html", "/"))
        self.assertEqual(build.out_path("404"), ("404.html", "/404.html"))
        self.assertEqual(build.out_path("research"), ("research/index.html", "/research/"))
        self.assertEqual(build.out_path("projects/x"), ("projects/x/index.html", "/projects/x/"))

    def test_nav_always_lists_everything_in_order(self):
        nav = build.nav_html("about")
        self.assertIn('href="/about/" aria-current="page"', nav)
        self.assertEqual(re.findall(r'href="([^"]+)"', nav),
                         ["/research/", "/commonplace/", "/writing/", "/about/", "/cv.pdf"])
        self.assertIn('href="/commonplace/" aria-current="page">Commonplace', build.nav_html("commonplace"))
        self.assertEqual(build.nav_html("").count("aria-current"), 0)

    def test_no_publishing_thresholds(self):
        self.assertFalse(hasattr(build, "WRITING_NAV_AT"))
        self.assertFalse(hasattr(build.cp, "VISIBLE_AT"))

    def test_body_class(self):
        self.assertEqual(build.body_class({"class": "home"}), ' class="home"')
        self.assertEqual(build.body_class({}), "")
        for bad in ("Home", "home page", 'x" onload="y'):
            with self.subTest(bad=bad), self.assertRaises(build.BuildError):
                build.body_class({"class": bad})

    def test_feed_links(self):
        self.assertEqual(build.feed_links(False, False), "")
        self.assertEqual(build.feed_links(True, True).count('rel="alternate"'), 2)
        self.assertIn('href="/commonplace/feed.xml"', build.feed_links(False, True))
        self.assertNotIn('href="/feed.xml"', build.feed_links(False, True))

    def test_feed_items_and_channel(self):
        items = [build.FeedItem("A & B", "https://garrettthrash.com/commonplace/a/", "Sum.", dt.date(2027, 1, 12))]
        rss = ET.fromstring(build.feed_xml("Commonplace", "/commonplace/", "/commonplace/feed.xml", items))
        self.assertEqual(rss.findtext("channel/title"), "Garrett W. Thrash: Commonplace")
        self.assertEqual(rss.findtext("channel/link"), "https://garrettthrash.com/commonplace/")
        self.assertEqual(rss.findtext("channel/item/title"), "A & B")
        self.assertEqual(rss.findtext("channel/item/pubDate"), "Tue, 12 Jan 2027 12:00:00 +0000")

    def test_now_label_and_age(self):
        label, age = build.now_label("2026-10", dt.date(2026, 11, 17))
        self.assertEqual((label, age), ("October 2026", 47))
        with self.assertRaises(build.BuildError):
            build.now_label("Oct 2026", dt.date(2026, 11, 17))

    def test_redirect_points_at_new_address(self):
        html = build.redirect_html("/about/#talks", {"teaching": "/about/#teaching"})
        self.assertIn('content="0; url=/about/#talks"', html)
        self.assertIn('href="https://garrettthrash.com/about/"', html)
        self.assertIn('{"teaching": "/about/#teaching"}[location.hash.slice(1)] || "/about/#talks"', html)

    def test_missing_anchors(self):
        outputs = {"about/index.html": '<h2 id="talks">', "index.html": ""}
        self.assertEqual(build.missing_anchors(outputs, ["/about/#talks", "/", "/about/#gone", "/nope/"]),
                         ["/about/#gone", "/nope/"])


def post(slug: str, date: str, external: str = "", outlet: str = "", updated: str = "",
         draft: bool = False) -> build.Post:
    """A made-up post; its title is its slug with spaces and its summary 'About <slug>.'."""
    return build.Post(path=Path(f"{slug}.md"), slug=slug, title=slug.replace("-", " "), summary=f"About {slug}.",
                      date=dt.date.fromisoformat(date), external=external, outlet=outlet,
                      updated=dt.date.fromisoformat(updated) if updated else None, draft=draft)


def cp_entry(slug: str, added: str) -> build.cp.Entry:
    """A made-up commonplace entry."""
    return build.cp.Entry(slug=slug, title=slug, summary=f"About {slug}.", types=("derivation",),
                          topics=("statistics",), added=dt.date.fromisoformat(added), updated=None,
                          source=Path(f"{slug}.md"))


class HomeSectionTests(unittest.TestCase):
    def test_empty_sections_say_coming_soon(self):
        self.assertEqual(build.writing_recent([]), '<h2 id="writing">Writing</h2>\n<p>Coming soon.</p>')
        self.assertEqual(build.commonplace_recent(()), '<h2 id="commonplace">Commonplace</h2>\n<p>Coming soon.</p>')

    def test_writing_section_shows_the_three_newest(self):
        posts = [post(f"p{i}", f"2027-01-0{i}") for i in range(5, 0, -1)]            # newest first
        html = build.writing_recent(posts)
        self.assertTrue(html.startswith('<h2 id="writing">Writing</h2>\n<div class="cards">'))
        self.assertEqual([s for s in ("p5", "p4", "p3", "p2", "p1") if f"/writing/{s}/" in html], ["p5", "p4", "p3"])
        self.assertIn('<div class="card"><p>January 5, 2027</p><p><a href="/writing/p5/">p5</a></p>'
                      '<p>About p5.</p></div>', html)
        self.assertTrue(html.endswith('<p><a href="/writing/">All writing</a></p>'))

    def test_commonplace_section_shows_the_three_newest(self):
        entries = tuple(cp_entry(f"e{i}", f"2027-01-0{i}") for i in range(1, 6))
        html = build.commonplace_recent(entries)
        self.assertTrue(html.startswith('<h2 id="commonplace">Commonplace</h2>\n<div class="cards">'))
        self.assertEqual([s for s in ("e5", "e4", "e3", "e2", "e1") if f"/commonplace/{s}/" in html], ["e5", "e4", "e3"])
        self.assertIn('<p>Derivation • Jan 2027</p><p><a href="/commonplace/e5/">e5</a></p><p>About e5.</p>', html)
        self.assertTrue(html.endswith('<p><a href="/commonplace/">All entries</a></p>'))


class WritingTests(unittest.TestCase):
    def test_empty_writing_page_has_both_sections_coming_soon(self):
        self.assertEqual(build.writing_index([]),
                         '<h2 id="essays">Essays</h2>\n<p>Coming soon.</p>\n'
                         '<h2 id="published-elsewhere">Published Elsewhere</h2>\n<p>Coming soon.</p>')

    def test_essays_and_pieces_elsewhere_are_listed_apart(self):
        posts = [post("newer", "2027-03-01"), post("op-ed", "2027-02-01", "https://example.org/op-ed", "The Outlet"),
                 post("older", "2027-01-01")]
        html = build.writing_index(posts)
        essays, elsewhere = html.split('<h2 id="published-elsewhere">')
        self.assertLess(essays.index("/writing/newer/"), essays.index("/writing/older/"))
        self.assertNotIn("op-ed", essays)
        self.assertIn('<p>February 1, 2027</p><p><a href="https://example.org/op-ed">op ed</a></p>'
                      '<p><em>The Outlet</em> • About op-ed.</p>', elsewhere)
        self.assertNotIn("Coming soon.", html)

    def test_reading_time(self):
        def words(n: int) -> str:
            return "<p>" + "word " * n + "</p>"

        self.assertEqual(build.reading_minutes(""), 1)
        self.assertEqual(build.reading_minutes(words(230)), 1)
        self.assertEqual(build.reading_minutes(words(231)), 2)
        self.assertEqual(build.reading_minutes(words(690)), 3)
        hidden = "<!-- " + "note " * 500 + "-->" + '<a href="https://example.org/a/very/long/url">two words</a>'
        self.assertEqual(build.reading_minutes(hidden + words(228)), 1)        # 230 words: the link text counts,
        self.assertEqual(build.reading_minutes(hidden + words(229)), 2)        # comments and tags don't

    def test_meta_line(self):
        self.assertEqual(build.post_meta(post("a", "2027-01-12"), 4), '<p class="meta">January 12, 2027 • 4 min read</p>')
        self.assertEqual(build.post_meta(post("a", "2027-01-12", updated="2027-02-03", draft=True), 1),
                         '<p class="meta">Draft • January 12, 2027 • updated February 3, 2027 • 1 min read</p>')

    def test_previous_and_next_skip_pieces_elsewhere(self):
        first, elsewhere, middle, last = (post("first", "2027-01-01"), post("ext", "2027-01-15", "https://x.org/", "X"),
                                          post("middle", "2027-02-01"), post("last", "2027-03-01"))
        posts = [last, middle, elsewhere, first]                                   # newest first, as built
        self.assertEqual(build.post_nav(middle, posts),
                         '<p class="post-nav">Previous: <a href="/writing/first/">first</a> • '
                         'Next: <a href="/writing/last/">last</a> • <a href="/writing/">All writing</a></p>')
        self.assertNotIn("Previous", build.post_nav(first, posts))
        self.assertNotIn("Next", build.post_nav(last, posts))
        self.assertEqual(build.post_nav(first, [first]), '<p class="post-nav"><a href="/writing/">All writing</a></p>')

    def test_post_front_matter_problems(self):
        good = {"title": "T", "summary": "S", "date": "2027-01-12"}
        self.assertEqual(build.post_problems(good), [])
        self.assertEqual(build.post_problems({**good, "updated": "2027-02-01"}), [])
        self.assertEqual(build.post_problems({"title": "T"}), ["missing `date`", "missing `summary`"])
        self.assertEqual(build.post_problems({**good, "date": "Jan 12", "updated": "soon"}),
                         ["`date` must be YYYY-MM-DD, got 'Jan 12'", "`updated` must be YYYY-MM-DD, got 'soon'"])
        self.assertEqual(build.post_problems({**good, "updated": "2027-01-01"}), ["`updated` is earlier than `date`"])
        self.assertEqual(build.post_problems({**good, "external": "https://x.org/"}),
                         ["`external` and `outlet` go together: give both or neither"])

    def test_make_post(self):
        p = build.make_post(Path("a-post.md"), {"title": "T", "summary": "S", "date": "2027-01-12",
                                                "updated": "2027-02-03", "draft": True})
        self.assertEqual((p.slug, p.url, p.updated, p.draft), ("a-post", "/writing/a-post/", dt.date(2027, 2, 3), True))
        ext = build.make_post(Path("x.md"), {"title": "T", "summary": "S", "date": "2027-01-12",
                                             "external": "https://x.org/", "outlet": "X"})
        self.assertEqual((ext.url, ext.updated, ext.draft), ("https://x.org/", None, False))


class ManifestTests(unittest.TestCase):
    def test_prune_removes_only_files_no_longer_built(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "build-manifest.txt"
            build.write_outputs({"a/index.html": "a", "b.html": "b"}, root)
            build.prune_stale({"a/index.html": "a", "b.html": "b"}, manifest, root)
            removed = build.prune_stale({"b.html": "b"}, manifest, root)
            self.assertEqual(removed, ["a/index.html"])
            self.assertFalse((root / "a").exists())
            self.assertTrue((root / "b.html").exists())
            self.assertEqual(manifest.read_text(), "b.html\n")

    def test_prune_never_touches_sources_or_files_outside(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.html"
            outside.write_text("keep")
            root = Path(tmp) / "site"
            (root / "templates").mkdir(parents=True)
            (root / "templates" / "base.html").write_text("keep")
            (root / "notes.md").write_text("keep")
            manifest = root / "build-manifest.txt"
            manifest.write_text("../outside.html\ntemplates/base.html\nnotes.md\n" + str(outside) + "\n")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(build.prune_stale({}, manifest, root), [])
            self.assertEqual(err.getvalue().count("left alone"), 4)
            self.assertTrue(outside.exists())
            self.assertTrue((root / "templates" / "base.html").exists())
            self.assertTrue((root / "notes.md").exists())

    def test_prune_rejects_disguised_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "templates").mkdir()
            (root / "templates" / "base.html").write_text("keep")
            (root / "index.html").write_text("fresh")
            manifest = root / "build-manifest.txt"
            manifest.write_text("./templates/base.html\n./index.html\ntemplates//base.html\n")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(build.prune_stale({"index.html": "fresh"}, manifest, root), [])
            self.assertTrue((root / "templates" / "base.html").exists())
            self.assertTrue((root / "index.html").exists())

    def test_commonplace_sources_and_drafts_are_never_pruned(self):
        self.assertFalse(build.prunable("commonplace/entries/x.html"))
        self.assertFalse(build.prunable("drafts/_site/index.html"))
        self.assertTrue(build.prunable("commonplace/index.html"))
        self.assertTrue(build.prunable("commonplace/feed.xml"))

    def test_manifest_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "build-manifest.txt"
            build.write_outputs({"a b/index.html": "x"}, root)
            build.prune_stale({"a b/index.html": "x"}, manifest, root)
            self.assertEqual(build.prune_stale({}, manifest, root), ["a b/index.html"])


class PreviewTests(unittest.TestCase):
    def test_preview_replaces_only_its_own_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "drafts"
            (drafts / "commonplace").mkdir(parents=True)
            (drafts / "commonplace" / "staged.md").write_text("keep")
            (drafts / "_site").mkdir()
            (drafts / "_site" / "stale.html").write_text("old")
            build.write_preview({"index.html": "new"}, drafts / "_site", drafts)
            self.assertEqual((drafts / "_site" / "index.html").read_text(), "new")
            self.assertFalse((drafts / "_site" / "stale.html").exists())
            self.assertTrue((drafts / "commonplace" / "staged.md").exists())

    def test_preview_refuses_folders_outside_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "drafts"
            (drafts / "commonplace").mkdir(parents=True)
            for out in (drafts, Path(tmp), Path(tmp) / "site", drafts / ".." / "elsewhere"):
                with self.assertRaises(build.BuildError):
                    build.write_preview({"index.html": "x"}, out, drafts)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["drafts"])
            self.assertTrue((drafts / "commonplace").exists())


class CheckSiteTests(unittest.TestCase):
    def test_wording(self):
        problems = check_site.wording_problems("<p>For organisers — and modelling</p>")
        self.assertEqual(len(problems), 3)
        self.assertEqual(check_site.wording_problems("<p>For organizers and modeling</p>"), [])

    def test_staging_comments_are_banned(self):
        self.assertEqual(check_site.wording_problems("<!-- CHECK: is this right? --><p>x</p>"), ["banned 'CHECK:'"])

    def test_commonplace_pages_are_checked_and_the_preview_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("index.html", "commonplace/index.html", "commonplace/x/index.html",
                        "commonplace/paths/p/index.html", "drafts/_site/index.html"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("")
            found = [p.relative_to(root).as_posix() for p in check_site.site_pages(root)]
            self.assertEqual(found, ["commonplace/index.html", "commonplace/paths/p/index.html",
                                     "commonplace/x/index.html", "index.html"])

    def test_commonplace_feed_must_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sitemap.xml").write_text("<urlset/>")
            (root / "commonplace").mkdir()
            (root / "commonplace" / "feed.xml").write_text("<rss><channel></rss>")
            problems = check_site.xml_problems(root)
            self.assertEqual(len(problems), 1)
            self.assertTrue(problems[0].startswith("commonplace/feed.xml:"))

    def test_links_and_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "about").mkdir()
            (root / "about" / "index.html").write_text('<h2 id="talks">Talks</h2>')
            page = root / "index.html"
            ok = check_site.link_problems(page, '<a href="/about/#talks">x</a>', root)
            bad = check_site.link_problems(page, '<a href="/about/#nope">x</a><a href="/gone/">y</a>', root)
            self.assertEqual(ok, [])
            self.assertEqual(len(bad), 2)
            single = check_site.link_problems(page, "<a href='/gone/'>x</a>", root)
            same_site = check_site.link_problems(page, '<a href="https://garrettthrash.com/gone/">x</a>', root)
            self.assertEqual((len(single), len(same_site)), (1, 1))

    def test_duplicate_ids(self):
        problems = check_site.head_problems('<h1 id="a">x</h1><h2 id="a">y</h2>')
        self.assertIn("duplicate id 'a'", problems)


class ServeTests(unittest.TestCase):
    def test_overlay_first_then_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay = root / "drafts" / "_site"
            for rel in ("drafts/_site/index.html", "drafts/_site/commonplace/index.html", "index.html", "style.css"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(rel)
            self.assertEqual(serve.pick("", overlay, root), overlay / "index.html")
            self.assertEqual(serve.pick("commonplace/", overlay, root), overlay / "commonplace" / "index.html")
            self.assertEqual(serve.pick("style.css", overlay, root), root / "style.css")
            self.assertEqual(serve.pick("missing.png", overlay, root), root / "missing.png")
            # A folder without its slash: the server answers with a redirect to add it.
            self.assertEqual(serve.pick("commonplace", overlay, root), overlay / "commonplace")

    def test_unsafe_paths_are_refused(self):
        for bad in ("../secret", "a/../../b", "/etc/passwd"):
            with self.assertRaises(ValueError):
                serve.pick(bad, Path("overlay"), Path("root"))

    def test_port(self):
        self.assertEqual(serve.parse_port([]), 8000)
        self.assertEqual(serve.parse_port(["8001"]), 8001)
        with self.assertRaises(SystemExit):
            serve.parse_port(["eight"])


# ---------- commonplace book fixtures (real pandoc) ---------------------------------------------

def book_index(path_entries: list[str]) -> str:
    """commonplace/index.md for a made-up book: two topics, a reading path if any entries, an intro."""
    paths = (f"paths:\n  - slug: fixture-path\n    title: Fixture Path\n    entries: [{', '.join(path_entries)}]\n"
             if path_entries else "paths: []\n")
    return ("---\ntitle: Commonplace\ndescription: Fixture notes for tests.\ntopics:\n"
            "  - slug: signal-processing\n    title: Signal Processing\n"
            "  - slug: statistics\n    title: Statistics\n" + paths + "---\n\nA fixture introduction.\n")


def entry_source(title: str, added: str, topics: str = "[signal-processing]", kind: str = "note",
                 body: str = "Fixture text.") -> str:
    """The Markdown of a made-up commonplace entry."""
    return (f"---\ntitle: {title}\nsummary: Summary of {title}.\ntype: {kind}\ntopics: {topics}\n"
            f"added: {added}\n---\n\n{body}\n")


def make_book(root: Path, entries: dict[str, str], drafts: dict[str, str] | None = None,
              path_entries: list[str] | None = None) -> tuple[Path, Path, Path]:
    """Write a book under root; return (book folder, published entries folder, drafts folder)."""
    book_dir, entries_dir, drafts_dir = root / "commonplace", root / "commonplace" / "entries", root / "drafts"
    entries_dir.mkdir(parents=True)
    drafts_dir.mkdir()
    (book_dir / "index.md").write_text(book_index(path_entries or []))
    for folder, sources in ((entries_dir, entries), (drafts_dir, drafts or {})):
        for slug, text in sources.items():
            (folder / f"{slug}.md").write_text(text)
    return book_dir, entries_dir, drafts_dir


FAKE_PUBS = {"fixture2027": {"type": "article", "key": "fixture2027", "title": "A fixture article",
                             "author": "Thrash, Garrett W.", "date": "2026", "journaltitle": "Fixture Journal"}}

# A two-page site. Building the real pages too would cost about 4 seconds a build (pandoc starts in
# about 0.2 s, twice per page), on every ./build.sh; test_home_has_the_tokens guards the real Home.
FIXTURE_PAGES = {
    "home.md": "---\ntitle: Home\ndescription: Fixture home.\nheading: false\nclass: home\n---\n\n<h1>Home</h1>\n\n"
               "[All publications](/publications/)\n\n<!-- writing:recent -->\n\n<!-- commonplace:recent -->\n",
    "research.md": "---\ntitle: Research\ndescription: Fixture research.\nnav: research\n---\n\nText.\n",
}


def post_source(title: str, date: str, words: int = 10, extra: str = "") -> str:
    """The Markdown of a made-up post with `words` words of body text."""
    return f"---\ntitle: {title}\nsummary: Summary of {title}.\ndate: {date}\n{extra}---\n\n" + "word " * words + "\n"


POSTS = {
    "first-essay": post_source("First Essay", "2027-01-01", words=300),
    "second-essay": post_source("Second Essay", "2027-02-01", extra="updated: 2027-02-10\n"),
    "op-ed": post_source("An Op-Ed", "2027-01-15", extra="external: https://example.org/op-ed\noutlet: The Outlet\n"),
    "unfinished": post_source("Unfinished", "2027-03-01", extra="draft: true\n"),
}


THREE = {
    "fixture-a": entry_source("Fixture A", "2027-01-01", body="Math $x^2$ and a citation.\n\n<!-- pubs:keys fixture2027 -->"),
    "fixture-b": entry_source("Fixture B", "2027-01-02", topics="[signal-processing, statistics]", kind="[derivation, code]"),
    "fixture-c": entry_source("Fixture C", "2027-01-03", topics="[statistics]"),
}


@unittest.skipUnless(shutil.which("pandoc"), "needs pandoc")
class ReadBookTests(unittest.TestCase):
    def test_every_problem_is_reported_at_once(self):
        entries = {
            "bad-type": entry_source("Bad type", "2027-01-01", kind="poem"),
            "leftovers": entry_source("Leftovers", "2027-01-01", body="<!-- CHECK: source? -->\n\nSee [[donoghue2020]]."),
            "Bad_Name": entry_source("Bad name", "2027-01-01"),
            "twice": entry_source("Twice", "2027-01-01"),
        }
        drafts = {"twice": entry_source("Twice", "2027-01-01"),
                  "drafty": entry_source("Drafty", "2027-01-01", body="<!-- CHECK: reword -->\n\nText.")}
        with tempfile.TemporaryDirectory() as tmp:
            dirs = make_book(Path(tmp), entries, drafts, path_entries=["twice", "ghost"])
            with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(build.BuildError) as caught:
                build.read_book(True, *dirs)
        message = str(caught.exception)
        for expected in ("bad-type.md: unknown type 'poem'", "leftovers.md: 1 CHECK comment(s)",
                         "leftovers.md: vault wikilinks", "Bad_Name.md: file name 'Bad_Name'",
                         "'twice' is both published", "path 'fixture-path' lists 'ghost', which is not an entry"):
            self.assertIn(expected, message)
        self.assertNotIn("drafty", message)                      # leftovers in a draft only warn
        self.assertIn("drafty.md: 1 CHECK comment(s)", err.getvalue())


@unittest.skipUnless(shutil.which("pandoc"), "needs pandoc")
class SiteBuildTests(unittest.TestCase):
    """The whole build, with real pandoc, run on a two-page fixture site, temporary posts and a temporary book."""

    def build_site(self, entries: dict[str, str], drafts: dict[str, str] | None = None,
                   preview: bool = False, posts: dict[str, str] | None = None) -> tuple[dict[str, str], build.cp.Book]:
        """build.build() with the pages, posts, book and bibliography swapped for fixtures."""
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as patches:
            book_dir, entries_dir, drafts_dir = make_book(Path(tmp), entries, drafts,
                                                          ["fixture-b", "fixture-a"] if entries else [])
            pages, posts_dir = Path(tmp) / "pages", Path(tmp) / "posts"
            pages.mkdir()
            posts_dir.mkdir()
            for name, text in FIXTURE_PAGES.items():
                (pages / name).write_text(text)
            for slug, text in (posts or {}).items():
                (posts_dir / f"{slug}.md").write_text(text)
            fixtures = {"PAGES": pages, "POSTS": posts_dir, "REDIRECTS": {}, "BOOK": book_dir,
                        "ENTRIES": entries_dir, "DRAFT_ENTRIES": drafts_dir,
                        "DRAFT_POSTS": Path(tmp) / "draft-posts"}   # never the real drafts/writing/
            for name, value in fixtures.items():
                patches.enter_context(mock.patch.object(build, name, value))
            patches.enter_context(mock.patch.object(build, "read_publications", return_value=FAKE_PUBS))
            outputs, _, _, book = build.build(preview)
        return outputs, book

    def test_home_has_the_tokens(self):
        """The fixture Home stands in for the real one, so the real one must keep its tokens and class."""
        home = (ROOT / "pages" / "home.md").read_text(encoding="utf-8")
        for token in ("\n<!-- pubs:compact ", "\n<!-- writing:recent -->\n", "\n<!-- commonplace:recent -->\n",
                      "\nclass: home\n", "\nheading: false\n", "\njsonld: true\n"):
            self.assertIn(token, home)
        self.assertLess(home.index("pubs:compact"), home.index("writing:recent"))
        self.assertLess(home.index("writing:recent"), home.index("commonplace:recent"))

    def test_empty_site_builds_the_structure_and_says_coming_soon(self):
        outputs, _ = self.build_site({})
        for path in ("writing/index.html", "commonplace/index.html", "commonplace/topics/signal-processing/index.html",
                     "commonplace/topics/statistics/index.html"):
            self.assertIn(path, outputs)
        self.assertEqual(sorted(p for p in outputs if p.endswith("feed.xml")), [])
        self.assertEqual(sorted(p for p in outputs if p.startswith(("commonplace/paths/", "writing/")) and
                                p != "writing/index.html"), [])
        writing = outputs["writing/index.html"]
        self.assertEqual(writing.count("<p>Coming soon.</p>"), 2)
        self.assertEqual(outputs["commonplace/index.html"].count("<p>Coming soon.</p>"), 2)   # one per topic
        self.assertIn("<p>Coming soon.</p>", outputs["commonplace/topics/statistics/index.html"])
        home = outputs["index.html"]
        self.assertIn('<body class="home">', home)
        self.assertIn('<h2 id="writing">Writing</h2>\n<p>Coming soon.</p>', home)
        self.assertIn('<h2 id="commonplace">Commonplace</h2>\n<p>Coming soon.</p>', home)
        for page in ("index.html", "research/index.html", "writing/index.html", "commonplace/index.html"):
            self.assertIn('<a href="/commonplace/"', outputs[page])          # both always in the navigation
            self.assertIn('<a href="/writing/"', outputs[page])
            self.assertNotIn('rel="alternate"', outputs[page])               # no feeds to link to
            self.assertIn('class="margin-neurons" aria-hidden="true"', outputs[page])
        self.assertIn("<body>", outputs["research/index.html"])
        for url in ("/writing/", "/commonplace/", "/commonplace/topics/signal-processing/"):
            self.assertIn(f"<loc>https://garrettthrash.com{url}</loc>", outputs["sitemap.xml"])

    def test_three_published_entries_appear_everywhere(self):
        outputs, _ = self.build_site(THREE)
        for path in ("commonplace/index.html", "commonplace/paths/fixture-path/index.html", "commonplace/feed.xml",
                     *(f"commonplace/{slug}/index.html" for slug in THREE)):
            self.assertIn(path, outputs)
        self.assertIn('<a href="/commonplace/">Commonplace</a>', outputs["research/index.html"])
        self.assertIn('<h2 id="commonplace">Commonplace</h2>', outputs["index.html"])
        self.assertIn('href="/commonplace/feed.xml"', outputs["research/index.html"])
        self.assertNotIn('href="/feed.xml"', outputs["research/index.html"])      # no posts, no writing feed
        index = outputs["commonplace/index.html"]
        self.assertIn("<p>A fixture introduction.</p>", index)
        self.assertIn('<p>2 entries</p><p><a href="/commonplace/topics/signal-processing/">', index)
        for heading in ('<h2 id="topics">', '<h2 id="recent">', '<h2 id="paths">'):
            self.assertIn(heading, index)
        topic = outputs["commonplace/topics/statistics/index.html"]
        self.assertLess(topic.index("/commonplace/fixture-c/"), topic.index("/commonplace/fixture-b/"))
        self.assertNotIn("/commonplace/fixture-a/", topic)
        self.assertEqual(len(re.findall(r"<h1[\s>]", topic)), 1)
        feed = ET.fromstring(outputs["commonplace/feed.xml"])
        self.assertEqual([item.findtext("title") for item in feed.iter("item")], ["Fixture C", "Fixture B", "Fixture A"])
        for url in ("/commonplace/", "/commonplace/fixture-a/", "/commonplace/paths/fixture-path/",
                    "/commonplace/topics/statistics/"):
            self.assertIn(f"<loc>https://garrettthrash.com{url}</loc>", outputs["sitemap.xml"])
        page = outputs["commonplace/fixture-a/index.html"]
        self.assertEqual(len(re.findall(r"<h1[\s>]", page)), 1)
        self.assertIn('<a href="/commonplace/topics/signal-processing/">Signal Processing</a>', page)   # breadcrumb
        self.assertIn("Fixture Journal", page)                   # publication tokens work in entries
        self.assertIn("<math", page)                             # math rendered to MathML
        self.assertIn('Previous: <a href="/commonplace/fixture-b/">', page)

    def test_fewer_than_three_entries_are_published(self):
        """The old rule hid the book until three entries were published; now any entry shows."""
        two = {slug: THREE[slug] for slug in ("fixture-a", "fixture-b")}
        outputs, book = self.build_site(two, {"broken": "---\ntitle: x\n---\n"})
        self.assertEqual([e.slug for e in book.entries], ["fixture-a", "fixture-b"])   # drafts unread outside preview
        self.assertIn("commonplace/fixture-a/index.html", outputs)
        self.assertIn("commonplace/feed.xml", outputs)
        self.assertIn("/commonplace/fixture-a/", outputs["index.html"])

    def test_posts_here_and_elsewhere(self):
        outputs, _ = self.build_site({}, posts=POSTS)
        self.assertEqual(sorted(p for p in outputs if p.startswith("writing/")),
                         ["writing/first-essay/index.html", "writing/index.html", "writing/second-essay/index.html"])
        index = outputs["writing/index.html"]
        essays, elsewhere = index.split('<h2 id="published-elsewhere">')
        self.assertLess(essays.index("/writing/second-essay/"), essays.index("/writing/first-essay/"))
        self.assertIn('<a href="https://example.org/op-ed">An Op-Ed</a></p><p><em>The Outlet</em>', elsewhere)
        self.assertNotIn("Unfinished", index)                                      # drafts stay out
        first = outputs["writing/first-essay/index.html"]
        self.assertIn('<p class="meta">January 1, 2027 • 2 min read</p>', first)  # 300 words
        self.assertIn('Next: <a href="/writing/second-essay/">Second Essay</a> • <a href="/writing/">All writing</a>',
                      first)
        second = outputs["writing/second-essay/index.html"]
        self.assertIn('<p class="meta">February 1, 2027 • updated February 10, 2027 • 1 min read</p>', second)
        self.assertIn('Previous: <a href="/writing/first-essay/">First Essay</a>', second)
        feed = ET.fromstring(outputs["feed.xml"])
        self.assertEqual([(i.findtext("title"), i.findtext("link")) for i in feed.iter("item")],
                         [("Second Essay", "https://garrettthrash.com/writing/second-essay/"),
                          ("An Op-Ed", "https://example.org/op-ed"),
                          ("First Essay", "https://garrettthrash.com/writing/first-essay/")])
        self.assertIn('href="/feed.xml"', outputs["research/index.html"])
        self.assertIn("<loc>https://garrettthrash.com/writing/first-essay/</loc>", outputs["sitemap.xml"])
        self.assertIn('<a href="/writing/second-essay/">Second Essay</a>', outputs["index.html"])

    def test_preview_includes_draft_posts(self):
        outputs, _ = self.build_site({}, posts=POSTS, preview=True)
        self.assertIn("Draft • March 1, 2027", outputs["writing/unfinished/index.html"])
        self.assertIn("/writing/unfinished/", outputs["writing/index.html"])

    def test_bad_post_dates_stop_the_build_all_at_once(self):
        bad = {"a": post_source("A", "2027-13-01"), "b": post_source("B", "2027-01-02", extra="updated: 2027-01-01\n")}
        with self.assertRaises(build.BuildError) as caught:
            self.build_site({}, posts=bad)
        message = str(caught.exception)
        self.assertIn("a.md: `date` must be YYYY-MM-DD, got '2027-13-01'", message)
        self.assertIn("b.md: `updated` is earlier than `date`", message)

    def test_preview_shows_a_single_draft(self):
        draft = {"fixture-d": entry_source("Fixture D", "2027-01-04", body="<!-- CHECK: fixture -->\n\nText.")}
        with contextlib.redirect_stderr(io.StringIO()) as err:
            outputs, book = self.build_site({}, draft, preview=True)
        self.assertIn("fixture-d.md: 1 CHECK comment(s)", err.getvalue())
        self.assertIn("Draft • Note", outputs["commonplace/fixture-d/index.html"])
        self.assertIn('<a href="/commonplace/">Commonplace</a>', outputs["index.html"])
        self.assertIn("/commonplace/fixture-d/", outputs["index.html"])


if __name__ == "__main__":
    unittest.main()
