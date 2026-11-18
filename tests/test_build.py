"""Tests for the pure parts of build.py and tools/check-site.py.

Run from the repository root:  python3 -m unittest discover -s tests
"""
import contextlib
import datetime as dt
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402

_spec = importlib.util.spec_from_file_location("check_site", ROOT / "tools" / "check-site.py")
check_site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_site)

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


class PageTests(unittest.TestCase):
    def test_out_paths(self):
        self.assertEqual(build.out_path("home"), ("index.html", "/"))
        self.assertEqual(build.out_path("404"), ("404.html", "/404.html"))
        self.assertEqual(build.out_path("research"), ("research/index.html", "/research/"))
        self.assertEqual(build.out_path("projects/x"), ("projects/x/index.html", "/projects/x/"))

    def test_nav_marks_current(self):
        nav = build.nav_html("about", show_writing=False)
        self.assertIn('href="/about/" aria-current="page"', nav)
        self.assertNotIn("/writing/", nav)
        self.assertIn("/writing/", build.nav_html("research", show_writing=True))

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

    def test_manifest_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "build-manifest.txt"
            build.write_outputs({"a b/index.html": "x"}, root)
            build.prune_stale({"a b/index.html": "x"}, manifest, root)
            self.assertEqual(build.prune_stale({}, manifest, root), ["a b/index.html"])


class CheckSiteTests(unittest.TestCase):
    def test_wording(self):
        problems = check_site.wording_problems("<p>For organisers — and modelling</p>")
        self.assertEqual(len(problems), 3)
        self.assertEqual(check_site.wording_problems("<p>For organizers and modeling</p>"), [])

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


if __name__ == "__main__":
    unittest.main()
