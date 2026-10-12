"""Tests for build.py. Run with:  python3 -m unittest discover -s tests -v"""
import contextlib
import io
import pathlib
import sys
import tempfile
import unittest
import xml.dom.minidom

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import build  # noqa: E402

INDEX_MD = """# home

> tagline

Hello [other site](https://example.org), [notes](notes.html) and [mail](mailto:a@example.org).

---

## one

text

### sub

more

---

## two

![resume preview](resume.pdf)
"""

NOTES_MD = """# notes

## first post

*2026-01-02*

Body of the first post.

---

## second post

*2026-03-04*

Body of the second post.
"""

SITE_TOML = """
name = "Test Site"
description = "A <test> description"
address = "example.test"
url = "https://example.test/"
{extra}

[[pages]]
file = "index"
label = "home"

[[pages]]
file = "notes"
label = "notes"
"""


def make_project(root: pathlib.Path, extra: str = "") -> None:
    (root / "content").mkdir()
    (root / "static").mkdir()
    (root / "site.toml").write_text(SITE_TOML.format(extra=extra), encoding="utf-8")
    (root / "content" / "index.md").write_text(INDEX_MD, encoding="utf-8")
    (root / "content" / "notes.md").write_text(NOTES_MD, encoding="utf-8")
    (root / "static" / "style.css").write_text("body{margin:0}", encoding="utf-8")
    (root / "static" / "site.js").write_text("", encoding="utf-8")
    (root / "static" / "resume.pdf").write_bytes(b"%PDF-1.4\n")


def build_site(root: pathlib.Path, **kwargs) -> build.Site:
    site = build.Site(root, out=root / "out", **kwargs)
    with contextlib.redirect_stdout(io.StringIO()):
        site.build()
    return site


class HelperTests(unittest.TestCase):
    def test_external_links(self):
        src = ('<a href="https://example.org">x</a> <a href="notes.html">y</a> '
               '<a href="mailto:a@b.c">z</a> <a href="resume.pdf">p</a> '
               '<a class="ext" href="http://e.org">c</a> <a href="https://e.org" target="_self">t</a>')
        out = build.external_links(src)
        self.assertIn('<a href="https://example.org" target="_blank" rel="noopener noreferrer">', out)
        self.assertIn('<a href="resume.pdf" target="_blank"', out)
        self.assertIn('<a class="ext" href="http://e.org" target="_blank"', out)
        self.assertIn('<a href="notes.html">', out)
        self.assertIn('<a href="mailto:a@b.c">', out)
        self.assertIn('<a href="https://e.org" target="_self">', out)

    def test_collapsible_balanced_and_nested(self):
        body = ('<h1 id="a">A</h1><p>x</p><h2 id="b">B</h2><p>y</p><h3 id="c">C</h3><p>z</p>'
                '<hr /><h2 id="d">D</h2><p>w</p>')
        out = build.collapsible(body)
        self.assertEqual(out.count("<details"), out.count("</details>"))
        self.assertEqual(out.count("<details"), 4)
        # the rule sits outside every section
        self.assertNotIn("<hr", out[: out.index("</details>\n<hr")])
        self.assertIn('<summary><h2 id="b">B</h2></summary>', out)

    def test_collapsible_without_headings(self):
        self.assertEqual(build.collapsible("<p>plain</p>"), "<p>plain</p>")

    def test_flatten_levels(self):
        tree = [{"level": 1, "name": "a", "id": "a", "children": [
            {"level": 2, "name": "b", "id": "b", "children": [
                {"level": 3, "name": "c", "id": "c", "children": []}]}]}]
        self.assertEqual([t["name"] for t in build.flatten(tree)], ["a", "b"])


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        make_project(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_when_file_missing(self):
        (self.root / "site.toml").unlink()
        cfg = build.Config.load(self.root / "site.toml")
        self.assertEqual(cfg.pages, [("index", "home")])

    def test_unknown_setting_rejected(self):
        (self.root / "site.toml").write_text('bogus = 1\n[[pages]]\nfile = "index"\n')
        with self.assertRaises(SystemExit):
            build.Config.load(self.root / "site.toml")

    def test_home_page_must_be_index(self):
        (self.root / "site.toml").write_text('[[pages]]\nfile = "about"\n')
        with self.assertRaises(SystemExit):
            build.Config.load(self.root / "site.toml")

    def test_bad_pdf_preview_rejected(self):
        (self.root / "site.toml").write_text('pdf_preview = "nope"\n[[pages]]\nfile = "index"\n')
        with self.assertRaises(SystemExit):
            build.Config.load(self.root / "site.toml")


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, site, name):
        return (site.out / name).read_text(encoding="utf-8")

    def test_basic_build(self):
        make_project(self.root)
        site = build_site(self.root)
        index = self.read(site, "index.html")
        self.assertTrue((site.out / "notes.html").exists())
        self.assertTrue((site.out / "site.js").exists())      # static/ is copied
        self.assertIn("<title>Test Site</title>", index)
        self.assertIn("A &lt;test&gt; description", index)    # escaped
        self.assertIn('<style>body{margin:0}</style>', index)  # inline css
        self.assertIn('<a class="name" href="index.html">example.test</a>', index)
        self.assertIn('href="#one"', index)                    # section list built from headings
        self.assertIn('<a href="notes.html">notes</a>', index)
        self.assertIn('<a href="index.html" aria-current="page">home</a>', index)
        self.assertIn('<link rel="prefetch" href="notes.html">', index)
        self.assertEqual(index.count("<details"), index.count("</details>"))

    def test_notes_title_and_current_page(self):
        make_project(self.root)
        site = build_site(self.root)
        notes = self.read(site, "notes.html")
        self.assertIn("<title>notes - Test Site</title>", notes)
        self.assertIn('<a href="notes.html" aria-current="page">notes</a>', notes)

    def test_links_in_content(self):
        make_project(self.root)
        index = self.read(build_site(self.root), "index.html")
        self.assertIn('href="https://example.org" target="_blank" rel="noopener noreferrer"', index)
        self.assertIn('<a href="notes.html">notes</a>', index)
        self.assertNotIn('mailto:a@example.org" target', index)

    def test_pdf_viewer_embed(self):
        make_project(self.root)
        index = self.read(build_site(self.root), "index.html")
        self.assertIn('<details class="preview" open>', index)
        self.assertIn('<object data="resume.pdf#toolbar=0', index)

    def test_clean_urls(self):
        make_project(self.root)
        index = self.read(build_site(self.root, clean_urls=True), "index.html")
        self.assertIn('<a class="name" href="/">', index)
        self.assertIn('<a href="/notes" aria-current="page">notes</a>'.replace(' aria-current="page"', ""), index)
        self.assertIn("<a href=\"/notes\">notes</a> and", index)   # link written as notes.html in the Markdown
        self.assertNotIn("notes.html", index)
        self.assertIn('href="https://example.org"', index)         # other sites untouched

    def test_other_site_link(self):
        make_project(self.root)
        (self.root / "site.toml").write_text(
            'name = "T"\n[other_site]\nlabel = "blog"\nurl = "https://blog.example.test"\n'
            '[[pages]]\nfile = "index"\n[[pages]]\nfile = "notes"\n')
        index = self.read(build_site(self.root), "index.html")
        self.assertIn('<a class="ext" href="https://blog.example.test" target="_blank"', index)

    def test_feed_hidden_by_default_and_external(self):
        make_project(self.root)
        index = self.read(build_site(self.root), "index.html")
        self.assertNotIn("Atom feed", index)
        self.assertNotIn("atom+xml", index)
        (self.root / "site.toml").write_text(
            'feed_url = "https://blog.example.test/atom.xml"\n[[pages]]\nfile = "index"\n[[pages]]\nfile = "notes"\n')
        index = self.read(build_site(self.root), "index.html")
        self.assertIn('href="https://blog.example.test/atom.xml" title="Atom feed"', index)
        self.assertIn('rel="alternate" type="application/atom+xml"', index)

    def test_local_feed(self):
        make_project(self.root, extra='feed_page = "notes"')
        site = build_site(self.root, clean_urls=True)
        doc = xml.dom.minidom.parseString(self.read(site, "atom.xml"))
        titles = [e.getElementsByTagName("title")[0].firstChild.data for e in doc.getElementsByTagName("entry")]
        self.assertEqual(titles, ["second post", "first post"])    # newest first
        links = [e.getElementsByTagName("link")[0].getAttribute("href") for e in doc.getElementsByTagName("entry")]
        self.assertEqual(links[0], "https://example.test/notes#second-post")
        self.assertIn('href="atom.xml"', self.read(site, "index.html"))

    def test_missing_content_file(self):
        make_project(self.root)
        (self.root / "content" / "notes.md").unlink()
        with self.assertRaises(SystemExit):
            build_site(self.root)

    def test_stylesheet_link_when_not_inlined(self):
        make_project(self.root, extra="inline_css = false")
        index = self.read(build_site(self.root), "index.html")
        self.assertIn('<link rel="stylesheet" href="style.css">', index)

    def test_rebuild_clears_old_output(self):
        make_project(self.root)
        site = build_site(self.root)
        (site.out / "stale.html").write_text("old")
        with contextlib.redirect_stdout(io.StringIO()):
            site.build()
        self.assertFalse((site.out / "stale.html").exists())


if __name__ == "__main__":
    unittest.main()
