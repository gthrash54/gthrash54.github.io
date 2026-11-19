"""Tests for commonplace.py: the entry checks, ordering and HTML of the commonplace book.

Run from the repository root:  python3 -m unittest discover -s tests
"""
import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import commonplace as cp  # noqa: E402

TOPICS = (cp.Topic("signal-processing", "Signal Processing"), cp.Topic("statistics", "Statistics"),
          cp.Topic("basal-ganglia", "Basal Ganglia"))
TOPIC_SLUGS = {t.slug for t in TOPICS}
META = {"title": "Band power", "summary": "One sentence.", "type": "note",
        "topics": ["signal-processing"], "added": "2027-01-12"}


def entry(slug: str, added: str = "2027-01-10", topics: tuple[str, ...] = ("signal-processing",),
          types: tuple[str, ...] = ("note",), draft: bool = False) -> cp.Entry:
    """A made-up entry; its title is its slug with spaces."""
    return cp.Entry(slug=slug, title=slug.replace("-", " "), summary="s", types=types, topics=topics,
                    added=dt.date.fromisoformat(added), updated=None, source=Path(f"{slug}.md"), draft=draft)


def book(entries: tuple[cp.Entry, ...], trails: tuple[cp.Trail, ...] = ()) -> cp.Book:
    """A made-up book around the given entries."""
    return cp.Book(title="Commonplace", description="d", intro="", topics=TOPICS, trails=trails, entries=entries)


class EntryProblemTests(unittest.TestCase):
    def test_good_entry_has_no_problems(self):
        self.assertEqual(cp.entry_problems("band-power", META, TOPIC_SLUGS), [])
        self.assertEqual(cp.entry_problems("band-power", {**META, "type": ["derivation", "code"],
                                                          "updated": "2027-02-01"}, TOPIC_SLUGS), [])

    def test_missing_fields_are_each_named(self):
        problems = cp.entry_problems("band-power", {"title": "Band power", "topics": []}, TOPIC_SLUGS)
        self.assertEqual(problems, ["missing `summary`", "missing `type`", "missing `topics`", "missing `added`"])

    def test_bad_and_reserved_file_names(self):
        self.assertIn("file name 'Band_Power' must be lowercase words joined by hyphens",
                      cp.entry_problems("Band_Power", META, TOPIC_SLUGS))
        self.assertIn("file name 'paths' is reserved", cp.entry_problems("paths", META, TOPIC_SLUGS))
        self.assertIn("file name 'topics' is reserved", cp.entry_problems("topics", META, TOPIC_SLUGS))

    def test_unknown_type_and_topic(self):
        problems = cp.entry_problems("x", {**META, "type": ["note", "poem"], "topics": ["astrology"]}, TOPIC_SLUGS)
        self.assertEqual(len(problems), 2)
        self.assertTrue(problems[0].startswith("unknown type 'poem'"))
        self.assertTrue(problems[1].startswith("unknown topic 'astrology'"))

    def test_dates(self):
        self.assertEqual(cp.entry_problems("x", {**META, "added": "Jan 12, 2027"}, TOPIC_SLUGS),
                         ["`added` must be YYYY-MM-DD, got 'Jan 12, 2027'"])
        self.assertEqual(cp.entry_problems("x", {**META, "updated": "2027-01-01"}, TOPIC_SLUGS),
                         ["`updated` is earlier than `added`"])


class TextProblemTests(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(cp.text_problems("Plain text with [a link](https://example.org)."), [])

    def test_check_comments_are_counted(self):
        text = "<!-- CHECK: reword -->\nText.\n<!-- CHECK: source? -->"
        self.assertEqual(cp.text_problems(text), ["2 CHECK comment(s) left from staging"])

    def test_wikilinks(self):
        self.assertEqual(cp.text_problems("As shown in [[donoghue2020]]."),
                         ["vault wikilinks ([[...]]) left in the text"])


class LabelTests(unittest.TestCase):
    def test_type_label(self):
        self.assertEqual(cp.type_label(("note",)), "Note")
        self.assertEqual(cp.type_label(("derivation", "code")), "Derivation and code")
        self.assertEqual(cp.type_label(("note", "derivation", "code")), "Note, derivation and code")


class NoGatingTests(unittest.TestCase):
    def test_there_is_no_publishing_threshold(self):
        self.assertFalse(hasattr(cp, "VISIBLE_AT"))
        self.assertFalse(hasattr(cp, "visible"))


class RelatedTests(unittest.TestCase):
    def test_most_shared_topics_first_then_newest(self):
        me = entry("me", topics=("signal-processing", "statistics"))
        one_old = entry("one-old", "2026-01-01", topics=("statistics",))
        one_new = entry("one-new", "2027-03-01", topics=("signal-processing",))
        both = entry("both", "2025-01-01", topics=("statistics", "signal-processing"))
        unrelated = entry("unrelated", topics=("basal-ganglia",))
        found = cp.related(me, (me, one_old, one_new, both, unrelated))
        self.assertEqual([e.slug for e in found], ["both", "one-new", "one-old"])

    def test_at_most_n(self):
        entries = tuple(entry(f"e{i}") for i in range(6))
        self.assertEqual(len(cp.related(entries[0], entries, n=2)), 2)


class TrailNavTests(unittest.TestCase):
    def setUp(self):
        self.entries = {s: entry(s) for s in ("first", "middle", "last", "elsewhere")}
        self.trails = (cp.Trail("reading", "Reading", ("first", "middle", "last")),)

    def nav(self, slug: str) -> str:
        return "".join(cp.trail_nav(self.entries[slug], self.trails, self.entries))

    def test_first_has_only_next(self):
        html = self.nav("first")
        self.assertIn("Reading</a>, 1 of 3", html)
        self.assertIn('Next: <a href="/commonplace/middle/">', html)
        self.assertNotIn("Previous", html)

    def test_middle_has_both(self):
        html = self.nav("middle")
        self.assertIn('Previous: <a href="/commonplace/first/">', html)
        self.assertIn('Next: <a href="/commonplace/last/">', html)

    def test_last_has_only_previous(self):
        html = self.nav("last")
        self.assertIn("3 of 3", html)
        self.assertIn('Previous: <a href="/commonplace/middle/">', html)
        self.assertNotIn("Next", html)

    def test_entry_on_no_path(self):
        self.assertEqual(self.nav("elsewhere"), "")


class ConfigProblemTests(unittest.TestCase):
    def test_good_config(self):
        trails = (cp.Trail("reading", "Reading", ("a", "b")),)
        self.assertEqual(cp.config_problems(TOPICS, trails, {"a", "b"}), [])

    def test_duplicate_topic(self):
        problems = cp.config_problems(TOPICS + (cp.Topic("statistics", "Again"),), (), set())
        self.assertEqual(problems, ["topic 'statistics' is listed twice"])

    def test_path_with_unknown_or_repeated_entry(self):
        trails = (cp.Trail("reading", "Reading", ("a", "ghost", "a")),)
        self.assertEqual(cp.config_problems(TOPICS, trails, {"a"}),
                         ["path 'reading' lists 'ghost', which is not an entry", "path 'reading' lists an entry twice"])

    def test_malformed_topic(self):
        problems = cp.config_problems((cp.Topic("Signal Processing", ""),), (), set())
        self.assertEqual(len(problems), 1)
        self.assertIn("lowercase-hyphen `slug` and a `title`", problems[0])


class IndexTests(unittest.TestCase):
    def test_empty_book_lists_every_topic_as_coming_soon(self):
        html = cp.index_body(book(()))
        self.assertIn('<h2 id="topics">Topics</h2>', html)
        for t in TOPICS:
            self.assertIn(f'<p>Coming soon.</p><p><a href="/commonplace/topics/{t.slug}/">{t.title}</a></p>', html)
        self.assertNotIn('id="recent"', html)
        self.assertNotIn('id="paths"', html)

    def test_topics_keep_config_order_and_show_counts(self):
        html = cp.index_body(book((entry("a", topics=("statistics",)), entry("b", topics=("statistics",)),
                                   entry("c", topics=("signal-processing", "statistics")))))
        self.assertIn('<p>1 entry</p><p><a href="/commonplace/topics/signal-processing/">', html)
        self.assertNotIn('<p>2 entries</p>', html)               # no topic has exactly 2
        self.assertIn('<p>3 entries</p><p><a href="/commonplace/topics/statistics/">', html)
        self.assertIn('<p>Coming soon.</p><p><a href="/commonplace/topics/basal-ganglia/">', html)
        self.assertLess(html.index("topics/signal-processing/"), html.index("topics/statistics/"))
        self.assertLess(html.index("topics/statistics/"), html.index("topics/basal-ganglia/"))

    def test_recent_lists_the_five_newest_with_types(self):
        entries = tuple(entry(f"e{i}", f"2027-01-0{i}", types=("derivation",)) for i in range(1, 8))
        html = cp.index_body(book(entries))
        recent = html[html.index('<h2 id="recent">Recent</h2>'):]
        self.assertEqual([s for s in ("e7", "e6", "e5", "e4", "e3", "e2", "e1") if f"/commonplace/{s}/" in recent],
                         ["e7", "e6", "e5", "e4", "e3"])
        self.assertLess(recent.index("/commonplace/e7/"), recent.index("/commonplace/e3/"))
        self.assertEqual(recent.count('<p class="kind">Derivation</p>'), 5)

    def test_paths_section_lists_paths_with_entries(self):
        trails = (cp.Trail("reading", "Reading", ("a",)), cp.Trail("empty", "Empty", ()))
        html = cp.index_body(book((entry("a"),), trails))
        self.assertIn('<h2 id="paths">Paths</h2>', html)
        self.assertIn('<p>1 entry</p><p><a href="/commonplace/paths/reading/">Reading</a>', html)
        self.assertNotIn("Empty", html)
        self.assertLess(html.index('id="recent"'), html.index('id="paths"'))


class TopicPageTests(unittest.TestCase):
    def test_topic_page_lists_its_entries_newest_first(self):
        stats = TOPICS[1]
        html = cp.topic_body(stats, (entry("old", "2026-01-01", topics=("statistics",)),
                                     entry("new", "2027-01-01", topics=("signal-processing", "statistics")),
                                     entry("elsewhere", topics=("basal-ganglia",))))
        self.assertIn('<p class="crumb"><a href="/commonplace/">Commonplace</a></p>', html)
        self.assertIn('<h1 class="page-title">Statistics</h1>', html)
        self.assertLess(html.index("/commonplace/new/"), html.index("/commonplace/old/"))
        self.assertIn('<div class="entry"><p>Jan 2027</p><p><a href="/commonplace/new/">new</a></p>'
                      '<p class="kind">Note</p></div>', html)
        self.assertNotIn("elsewhere", html)
        self.assertNotIn("Coming soon.", html)

    def test_empty_topic_says_coming_soon(self):
        html = cp.topic_body(TOPICS[2], (entry("a"),))
        self.assertTrue(html.endswith('<h1 class="page-title">Basal Ganglia</h1>\n<p>Coming soon.</p>'))

    def test_topic_url(self):
        self.assertEqual(TOPICS[0].url, "/commonplace/topics/signal-processing/")


class EntryPageTests(unittest.TestCase):
    def test_head_has_crumb_title_and_facts(self):
        e = cp.Entry("x", "A & B", "s", ("derivation", "code"), ("statistics",), dt.date(2027, 1, 12),
                     dt.date(2027, 2, 3), Path("x.md"), draft=True)
        html = cp.entry_head(e, {t.slug: t for t in TOPICS})
        self.assertIn('<p class="crumb"><a href="/commonplace/">Commonplace</a> • '
                      '<a href="/commonplace/topics/statistics/">Statistics</a></p>', html)
        self.assertNotIn("/commonplace/#", html)
        self.assertIn('<h1 class="page-title">A &amp; B</h1>', html)
        self.assertIn("Draft • Derivation and code • January 12, 2027 • updated February 3, 2027", html)


class CodeTests(unittest.TestCase):
    def test_brackets_in_code_are_not_wikilinks(self):
        text = "Index with `a[[0, 1]]`.\n\n```python\nb = a[[0, 1]]\n```\n"
        self.assertEqual(cp.text_problems(text), [])
        self.assertEqual(len(cp.text_problems("See [[Beta bursts]].")), 1)

    def test_longer_closing_fence_does_not_hide_prose(self):
        text = "```\ncode\n````\nSee [[Private note]].\n```\nmore code\n```\n"
        self.assertIn("vault wikilinks ([[...]]) left in the text", cp.text_problems(text))

    def test_unclosed_fence_is_a_problem(self):
        self.assertIn("a code fence is never closed", cp.text_problems("```\n[[hidden]]\n"))

    def test_false_date_is_rejected(self):
        meta = {"title": "T", "summary": "S", "type": "note", "topics": ["t"], "added": False}
        self.assertTrue(any("added" in p for p in cp.entry_problems("t", meta, {"t"})))


if __name__ == "__main__":
    unittest.main()
