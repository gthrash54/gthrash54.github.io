"""Tests for tools/stage.py and tools/promote.py, on fixture text (never the real vault).

Run from the repository root:  python3 -m unittest discover -s tests
"""
import datetime as dt
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402
import commonplace  # noqa: E402


def load_tool(name: str):
    """Import tools/<name>.py. It is registered in sys.modules first, which dataclasses need."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stage = load_tool("stage")
promote = load_tool("promote")

NOTE = """---
type: topic
topic: "Band power"
verified: false
sources: [smith2020spectra, doe2021beta]
---

# Band power

> Band power is the integral of the spectrum
> over a frequency band.

%% a private aside %%

## What is established
- Spectra have an aperiodic part [[smith2020spectra]].
- Beta comes in bursts [[doe2021beta]], as shown again in [[smith2020spectra|Smith]].
- Compare [[Multitaper spectral estimation|multitaper estimates]] and [[Phase-amplitude coupling#Methods]].
![[spectrum figure.png]]

> [!note] Measured in this archive, 2026-09-09
> Lines at 28 Hz in the lab recordings.
continued without a marker

After the callout.

## Open questions
- Whether the GPe exponent differs, from data already staged.

## Why it matters here
- The plan names the GPe exponent as open ground.

## Related topics
- [[Multitaper spectral estimation]]

## Sources
- [[smith2020spectra]]: a paper.

- [[Topics Index]] · [[Home]]
"""

KNOWN = {"smith2020spectra", "doe2021beta"}
TODAY = dt.date(2026, 11, 18)


def staged(text: str = NOTE, **kwargs):
    """stage_body on a fixture note."""
    return stage.stage_body(stage.split_front_matter(text)[1], KNOWN, **kwargs)


def fixture_draft() -> str:
    """The whole draft stage.py would write for NOTE: one citation found, one missing."""
    result = staged()
    meta = stage.entry_meta("Band power", ["signal-processing"], TODAY)
    header = stage.header_comment("11 - Topics/05 - X/Band power.md", TODAY, False, [])
    refs = {"smith2020spectra": {"authors": ["Ann Smith"], "title": "Spectra", "journal": "J", "year": "2020",
                                 "doi": "10.1/x"}, "doe2021beta": None}
    return stage.assemble_document(meta, header, result.body, stage.sources_section(list(result.cited), refs))


class AllowListTests(unittest.TestCase):
    def test_default_keeps_definition_and_what_is_established_only(self):
        result = staged()
        self.assertTrue(result.body.startswith("Band power is the integral of the spectrum\nover a frequency band."))
        self.assertIn("## What is established", result.body)
        self.assertIn("After the callout.", result.body)
        for private in ("Open questions", "GPe", "Why it matters", "Related topics", "Measured in this archive",
                        "Lines at 28 Hz", "continued without a marker", "a private aside", "# Band power", ">"):
            self.assertNotIn(private, result.body)
        self.assertEqual(result.kept, ("opening definition", 'section "What is established"'))
        dropped = "\n".join(result.dropped)
        for what in ('title heading "Band power"', 'section "Open questions"', 'section "Why it matters here"',
                     'section "Sources"', "callout [!note]", "1 comment(s)", "embed"):
            self.assertIn(what, dropped)

    def test_keep_adds_a_named_section(self):
        result = staged(keep=["open questions"])
        self.assertIn("## Open questions", result.body)
        self.assertNotIn("Why it matters", result.body)

    def test_keep_unknown_or_sources_fails(self):
        with self.assertRaises(stage.StageError):
            staged(keep=["Methods"])
        with self.assertRaises(stage.StageError):
            staged(keep=["Sources"])

    def test_all_keeps_sections_but_still_drops_private_markup(self):
        result = staged(keep_all=True)
        for kept in ("## Open questions", "## Why it matters here", "## Related topics", "- Multitaper spectral estimation"):
            self.assertIn(kept, result.body)
        for private in ("## Sources", "Measured in this archive", "a private aside", "Topics Index", "spectrum figure"):
            self.assertNotIn(private, result.body)

    def test_lead_without_a_blockquote_is_dropped(self):
        result = staged("# T\n\nA private sentence.\n\n## What is established\n- Fact.\n")
        self.assertNotIn("private", result.body)
        self.assertIn("no blockquote definition found", "\n".join(result.dropped))

    def test_headings_inside_code_do_not_split_sections(self):
        text = "## What is established\n```python\n# Open questions\nx = a[[0, 1]]  # %% not a comment\n```\n"
        result = staged(text)
        self.assertIn("# Open questions\nx = a[[0, 1]]  # %% not a comment", result.body)

    def test_setext_heading_starts_a_section(self):
        result = staged("## What is established\n- Fact.\n\nOpen questions\n--------------\n- A plan.\n")
        self.assertNotIn("A plan", result.body)

    def test_unclosed_code_fence_fails(self):
        with self.assertRaises(stage.StageError):
            staged("## What is established\n```\ncode\n## Open questions\n- A plan.\n")

    def test_each_heading_level_has_its_own_allow_list_decision(self):
        for level in range(1, 7):
            with self.subTest(level=level):
                hashes = "#" * level
                text = ("# Title\n\n> Definition.\n\n## What is established\nPublic fact.\n\n"
                        f"{hashes} Open questions\nPrivate question.\n\n"
                        f"{hashes} Sources\nPrivate source annotation.\n\n"
                        f"{hashes} What is established\nAnother fact.\n")
                result = staged(text)
                self.assertIn("Definition.", result.body)
                self.assertIn("Public fact.", result.body)
                self.assertIn(f"{'#' * max(2, level)} What is established\nAnother fact.", result.body)
                self.assertNotIn("Private", result.body)
                self.assertIn('section "Open questions"', "\n".join(result.dropped))
                self.assertIn('section "Sources"', "\n".join(result.dropped))
                for options in ({"keep": ["Open questions"]}, {"keep_all": True}):
                    explicit = staged(text, **options)
                    self.assertIn(f"{'#' * max(2, level)} Open questions", explicit.body)
                    self.assertIn("Private question.", explicit.body)
                    self.assertNotIn("Private source annotation.", explicit.body)

    def test_kept_subsection_does_not_allow_its_children(self):
        text = ("## What is established\nFact.\n### Methods\nMethod.\n"
                "#### Internal details\nPrivate detail.\n##### Sources\nPrivate source.\n")
        result = staged(text, keep=["Methods"])
        self.assertIn("### Methods\nMethod.", result.body)
        self.assertNotIn("Private", result.body)
        for title in ("Internal details", "Sources"):
            self.assertIn(f'section "{title}"', "\n".join(result.dropped))

    def test_setext_sources_are_always_dropped(self):
        for underline in ("===", "---"):
            result = staged(f"# Title\n\n## What is established\nFact.\n\nSources\n{underline}\nPrivate.",
                            keep_all=True)
            self.assertNotIn("Private", result.body)
            self.assertIn('section "Sources"', "\n".join(result.dropped))

    def test_invalid_backtick_info_string_is_not_a_fence(self):
        text = ("## What is established\n```bad`info\n<!-- private comment -->\n"
                "### Open questions\nPrivate question.\n")
        self.assertFalse(any(commonplace.code_mask(text.split("\n"))[0]))
        result = staged(text)
        self.assertNotIn("private comment", result.body)
        self.assertNotIn("Private question", result.body)

    def test_common_fence_rules_preserve_code_and_expose_following_sections(self):
        for opening, false_closers, closing in (("````python", ["```", "~~~~", "```` trailing"], "`````"),
                                                ("~~~text", ["~~", "```", "~~~ trailing"], "~~~~")):
            with self.subTest(opening=opening):
                code = "\n".join([opening, "### Sources", "<!-- code --> %% code %%",
                                  "> [!note] code", "![code][ref]", "[[code]]", "", "", *false_closers, closing])
                result = staged(f"## What is established\n{code}\n### Open questions\nPrivate question.")
                self.assertIn(code, result.body)
                self.assertNotIn("Private question", result.body)
                self.assertEqual(stage.checked_code_mask(code.split("\n")),
                                 commonplace.code_mask(code.split("\n"))[0])
                with self.assertRaises(stage.StageError):
                    staged(f"## What is established\n{opening}\ncode\n{false_closers[-1]}")


class PrivateMarkupTests(unittest.TestCase):
    def test_comments_inline_and_across_lines(self):
        lines = ["keep %%drop%% keep", "<!-- drop", "drop -->", "kept", "%%", "## drop", "%%after"]
        out, report = stage.strip_comments(lines)
        self.assertEqual(out, ["keep  keep", "kept", "after"])
        self.assertEqual(report, ["3 comment(s) (%% or <!-- -->)"])

    def test_unclosed_comment_hides_the_rest(self):
        out, report = stage.strip_comments(["kept", "%% private", "## Section", "text"])
        self.assertEqual(out, ["kept"])
        self.assertIn("unclosed", report[-1])

    def test_embeds_and_images_are_removed(self):
        out, report = stage.strip_private(["Text ![[fig.png]] here ![a](x.png)", "![[only.png]]"], "s")
        self.assertEqual(out, ["Text  here"])
        self.assertEqual(len(report), 2)

    def test_nav_lines(self):
        for nav in ("- [[Topics Index]] · [[Home]]", "[[Home]]", "[[A]] | [[B]]", "1. [[Literature Index]]"):
            self.assertTrue(stage.is_nav_line(nav), nav)
        for content in ("- [[Beta bursts]]", "See [[A]] and [[B]].", "- Plain text", "[[A]] [[B]] text"):
            self.assertFalse(stage.is_nav_line(content), content)

    def test_callout_runs_to_blank_line(self):
        lines = ["> [!warning]- Results", "> 28 Hz", "lazy line", "", "kept"]
        self.assertEqual(stage.strip_private(lines, "s")[0], ["", "kept"])

    def test_quotes_and_callouts_in_lists_are_dropped_with_continuations(self):
        for prefix in ("> ", "    > ", "- > ", "* > ", "+ > ", "1. > ", "2) > ", "  - 1. > > "):
            for marker in ("", "[!note] "):
                with self.subTest(prefix=prefix, marker=marker):
                    text = ("# Title\n\n> Definition.\n\n## What is established\nPublic fact.\n\n"
                            f"{prefix}{marker}Private opening.\n    > Private quote.\n"
                            "    Private continuation.\nLazy continuation.\n\nPublic ending.")
                    for keep_all in (False, True):
                        result = staged(text, keep_all=keep_all)
                        self.assertTrue(result.body.startswith("Definition."))
                        self.assertIn("Public fact.", result.body)
                        self.assertIn("Public ending.", result.body)
                        self.assertNotIn("Private", result.body)
                        self.assertNotIn("Lazy continuation", result.body)
                        kind = "callout [!note]" if marker else "blockquote"
                        self.assertIn(f'{kind} in "What is established" (4 lines)', result.dropped)

    def test_each_quote_block_is_reported_and_lead_callout_is_not_a_definition(self):
        result = staged("# T\n\n> [!note] Private lead.\n\n## What is established\n"
                        "> Private one.\n\n- > Private two.\n\nFact.", keep_all=True)
        self.assertNotIn("Private", result.body)
        self.assertEqual(sum("blockquote in" in drop for drop in result.dropped), 2)
        self.assertTrue(any("callout [!note]" in drop for drop in result.dropped))

    def test_quote_continuation_consumes_a_whole_fenced_block(self):
        lines = ["- > Private.", "  ```", "  hidden", "", "  more hidden", "  ```", "", "Fact."]
        out, report = stage.strip_private(lines, "s")
        self.assertEqual(out, ["", "Fact."])
        self.assertIn("blockquote in s (6 lines)", report)

    def test_adjacent_list_quotes_are_each_reported(self):
        out, report = stage.strip_private(["- > First.", "  > continuation", "- > Second."], "s")
        self.assertEqual(out, [])
        self.assertEqual(report, ["blockquote in s (2 lines)", "blockquote in s (1 lines)"])

    def test_all_image_forms_are_removed_outside_code(self):
        images = ["![[private.png]]", "![private](private.png)", "![private][ref]", "![private][]",
                  "![private]", '<img src="private.png">', "<IMG src='private.png' />",
                  '<img\n src="private.png"\n alt="a > b">', '![`private`][ref]',
                  '<img alt="`private`" src="private.png">']
        for markup in images:
            with self.subTest(markup=markup):
                result = staged(f"## What is established\nBefore {markup} after.\n")
                self.assertNotIn("private", result.body)
                self.assertNotIn("<img", result.body.lower())
                self.assertIn("Before", result.body)
                self.assertIn("after.", result.body)
                self.assertTrue(any("1 embed(s) or image(s)" in drop for drop in result.dropped))
                code = f"```html\n{markup}\n```"
                protected = staged(f"## What is established\n{code}\n")
                self.assertIn(code, protected.body)
        for inline in ('`![example][ref] <img src="example.png">`', '``![`example`][ref]``'):
            self.assertIn(inline, staged(f"## What is established\n{inline}").body)

    def test_images_in_kept_headings_are_removed(self):
        result = staged('## Heading ![private][ref] <img src="private.png">\nFact.', keep_all=True)
        self.assertNotIn("private", result.body)
        self.assertIn("## Heading", result.body)
        self.assertTrue(any("2 embed(s) or image(s)" in drop for drop in result.dropped))

    def test_fences_inside_removed_comments_do_not_hide_following_prose(self):
        for opener, closer in (("%%", "%%"), ("<!--", "-->")):
            result = staged(f"## What is established\nFact.\n{opener}\n```\n{closer}\n"
                            "![private]\n### Open questions\nPrivate question.")
            self.assertIn("Fact.", result.body)
            self.assertNotIn("private", result.body)
            self.assertNotIn("Private", result.body)

    def test_fence_exposed_by_comment_removal_preserves_code(self):
        lines = ["%% removed %%```", "<!-- code -->", "```"]
        out, _ = stage.strip_comments(lines)
        self.assertEqual(out, ["```", "<!-- code -->", "```"])


class LinkTests(unittest.TestCase):
    def test_links_and_citation_numbering(self):
        text = ("A [[smith2020spectra]] B [[doe2021beta]] C [[smith2020spectra|Smith]] "
                "D [[Note|alias]] E [[Note]] F [[Note#Heading]] G [[Folder/Deep note]] `[[code]]`")
        out, cited = stage.convert_links(text, KNOWN)
        self.assertEqual(out, "A [1] B [2] C Smith [1] D alias E Note F Note G Deep note `[[code]]`")
        self.assertEqual(cited, ["smith2020spectra", "doe2021beta"])

    def test_unknown_citekey_is_numbered_and_checked(self):
        out, cited = stage.convert_links("Claim [[nobody2019missing]].", KNOWN)
        self.assertEqual((out, cited), ("Claim [1].", ["nobody2019missing"]))
        sources = stage.sources_section(cited, {"nobody2019missing": None})
        self.assertEqual(sources.count(commonplace.CHECK), 2)          # the heading and the missing note
        self.assertIn("no literature note for citekey nobody2019missing", sources)

    def test_fixture_citations_in_document_order(self):
        result = staged()
        self.assertEqual(result.cited, ("smith2020spectra", "doe2021beta"))
        self.assertIn("aperiodic part [1].", result.body)
        self.assertIn("in Smith [1].", result.body)
        self.assertIn("Compare multitaper estimates and Phase-amplitude coupling.", result.body)
        self.assertNotIn("[[", result.body)


class ReferenceTests(unittest.TestCase):
    META = {"authors": ["Thomas Donoghue", "Matar Haller", "Erik J. Peterson"],
            "title": "Parameterizing neural power spectra", "journal": "Nature Neuroscience", "year": "2020",
            "doi": "https://doi.org/10.1038/s41593-020-00744-x", "pmid": "33230329"}

    def test_full_reference(self):
        self.assertEqual(stage.format_reference("k", self.META),
                         "Donoghue T, et al. Parameterizing neural power spectra. *Nature Neuroscience* (2020). "
                         "[doi](https://doi.org/10.1038/s41593-020-00744-x)")

    def test_two_authors_in_full_and_owner_in_bold(self):
        self.assertEqual(stage.format_authors(["Garrett W. Thrash", "Emily Wang"]), "**Thrash GW**, Wang E.")
        self.assertEqual(stage.format_authors(["Wang, Emily"]), "Wang E.")

    def test_fallback_links(self):
        no_doi = {"pmid": "123", "arxiv": "arXiv:2101.00001", "url": "https://x.org/a (b)"}
        self.assertEqual(stage.reference_link(no_doi), "[pubmed](https://pubmed.ncbi.nlm.nih.gov/123/)")
        self.assertEqual(stage.reference_link({"arxiv": "arXiv:2101.00001"}), "[arxiv](https://arxiv.org/abs/2101.00001)")
        self.assertEqual(stage.reference_link({"url": "https://x.org/a (b)"}), "[link](https://x.org/a%20%28b%29)")

    def test_missing_fields_are_checked_and_markup_escaped(self):
        ref = stage.format_reference("k", {"title": "The *real* [18F] story?"})
        self.assertIn(r"The \*real\* \[18F\] story?", ref)
        self.assertIn("has no authors, journal, year, DOI or link", ref)


class IdentifierTests(unittest.TestCase):
    FLAGGED = ["Recorded in uh3021.", "Case UG12 again.", "As in subject 4.", "Patient #12 improved.",
               "Participant 3 spoke.", "Check the MRN.", "DOB on file.", "Her date of birth.",
               "Seen 3/14/2025.", "Logged 2026-09-09.", "Record 1234567.", "From this archive.",
               "In our data.", "Our cohort shows it.", "Data in hand.", "Already staged.", "Still unpublished.",
               "Run on Cheaha.", "Uploaded to Box.", "Funded by UH3.", "The Walker lab found it."]

    def test_each_pattern_flags(self):
        for line in self.FLAGGED:
            self.assertTrue(stage.identifier_hits(line), line)

    def test_clean_lines_are_not_flagged(self):
        for line in ("Beta power falls 20% during movement [1].", "A box plot of 1/f slopes over 12 bands.",
                     "Use case-based reasoning."):
            self.assertEqual(stage.identifier_hits(line), [], line)

    def test_flag_goes_at_end_of_line(self):
        out, n = stage.flag_identifiers("- One uh3021 item\n- Clean item")
        self.assertEqual(n, 1)
        self.assertEqual(out, '- One uh3021 item <!-- CHECK: "uh3021" looks like a lab case ID -->\n- Clean item')


class DocumentTests(unittest.TestCase):
    def test_layout(self):
        text = fixture_draft()
        self.assertTrue(text.startswith('---\ntitle: "Band power"\nsummary: "CHECK: one sentence'))
        self.assertIn("type: note\ntopics: [\"signal-processing\"]\nadded: 2026-11-18\n---\n<!-- CHECK: staged", text)
        self.assertIn("verified: false", text)
        self.assertIn("## Sources <!-- CHECK:", text)
        self.assertIn("1. Smith A. Spectra. *J* (2020). [doi](https://doi.org/10.1/x)", text)
        self.assertIn("2. `doe2021beta` <!-- CHECK: no literature note", text)

    @unittest.skipUnless(shutil.which("pandoc"), "needs pandoc")
    def test_front_matter_builds_once_summary_is_written(self):
        text = fixture_draft().replace(stage.SUMMARY, "Band power mixes oscillations with the aperiodic slope.")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "band-power.md"
            path.write_text(text, encoding="utf-8")
            meta = build.plain_meta(build.read_meta(path))
        self.assertEqual(meta["topics"], ["signal-processing"])
        self.assertEqual(commonplace.entry_problems("band-power", meta, {"signal-processing"}), [])
        self.assertTrue(commonplace.text_problems(text))             # the header and Sources CHECKs remain

    def test_title_and_topics(self):
        self.assertEqual(stage.note_title({"topic": "Aperiodic exponent"}, "Other", "file"), "Aperiodic exponent")
        self.assertEqual(stage.note_title({}, None, "file"), "file")
        folders = {"signal-processing": "05 - Methods - signal processing", "statistics": "06 - Stats"}
        note = Path("11 - Topics/05 - Methods - signal processing/Aperiodic exponent.md")
        self.assertEqual(stage.choose_topics([], note, folders)[0], ["signal-processing"])
        self.assertEqual(stage.choose_topics(["statistics"], note, folders)[0], ["statistics"])
        with self.assertRaises(stage.StageError):
            stage.choose_topics(["nope"], note, folders)
        with self.assertRaises(stage.StageError):
            stage.choose_topics([], Path("11 - Topics/08 - Speech/Inner speech.md"), folders)


class FindNoteTests(unittest.TestCase):
    def test_vault_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            for rel in ("a/Beta bursts.md", "b/Beta bursts.md", "c/Unique.md", ".trash/Gone.md",
                        "99 - Archive/Old.md", ".obsidian/x.md"):
                (vault / rel).parent.mkdir(parents=True, exist_ok=True)
                (vault / rel).write_text("x")
            notes = stage.vault_notes(vault)
            self.assertEqual(sorted(p.as_posix() for p in notes), ["a/Beta bursts.md", "b/Beta bursts.md", "c/Unique.md"])
            self.assertEqual(stage.resolve_note("unique", notes), Path("c/Unique.md"))
            self.assertEqual(stage.resolve_note("b/Beta bursts", notes), Path("b/Beta bursts.md"))
            with self.assertRaises(stage.StageError) as ambiguous:
                stage.resolve_note("Beta bursts", notes)
            self.assertIn("a/Beta bursts.md", str(ambiguous.exception))
            self.assertIn("b/Beta bursts.md", str(ambiguous.exception))
            for skipped in ("Gone", "Old", "99 - Archive/Old.md"):
                with self.assertRaises(stage.StageError):
                    stage.resolve_note(skipped, notes)


class PromoteTests(unittest.TestCase):
    META = {"title": "Band power", "summary": "One sentence.", "type": "note",
            "topics": ["signal-processing"], "added": "2026-11-18"}
    TOPICS = {"signal-processing"}

    def problems(self, text="Clean text.", meta=None, published=frozenset()):
        return promote.promote_problems("band-power", meta or self.META, text, self.TOPICS, set(published))

    def test_clean_draft_passes(self):
        self.assertEqual(self.problems(), [])

    def test_blocks_check_wikilinks_topic_and_published(self):
        self.assertIn("CHECK", " ".join(self.problems("Text <!-- CHECK: rewrite -->")))
        self.assertIn("wikilinks", " ".join(self.problems("See [[Note]].")))
        self.assertIn("unknown topic", " ".join(self.problems(meta={**self.META, "topics": ["nope"]})))
        self.assertIn("already published", " ".join(self.problems(published={"band-power"})))

    def test_staged_draft_is_refused(self):
        self.assertIn("CHECK", " ".join(self.problems(fixture_draft())))


if __name__ == "__main__":
    unittest.main()
