#!/usr/bin/env python3
"""Static site builder: content/*.md + static/ -> public/

    python3 build.py                  build into public/
    python3 build.py --serve          build, then serve public/ at http://localhost:8000
    python3 build.py --clean-urls     links like /notes instead of notes.html (or set CLEAN_URLS=1)

Settings live in site.toml. See README.md for the full guide.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import functools
import html
import http.server
import os
import pathlib
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from urllib.parse import urljoin

import markdown
from markdown.extensions.toc import slugify

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

ROOT = pathlib.Path(__file__).resolve().parent

# Runs in <head> before first paint, so a saved light-theme choice does not flash dark.
# It also tells the browser which colour scheme to use for its own default background.
THEME_SNIPPET = (
    'document.documentElement.classList.add("js");'
    'try{var t=localStorage.getItem("theme");'
    'if(t==="light"||t==="dark"){document.documentElement.dataset.theme=t;'
    'document.querySelector("meta[name=color-scheme]").content=t}}catch(e){}'
)

TEMPLATE = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{description}
<meta name="color-scheme" content="dark">
<script>{theme_snippet}</script>
{styles}
{preload}
{prefetch}
{feed_head}
<script src="site.js" defer></script>
</head>
<body>

<header class="bar">
  <a class="name" href="{home}">{address}</a>
  <span class="meta">{status} · {updated}</span>
  <div class="tools">
    {feed_button}
    <button class="theme" type="button" aria-pressed="true" title="Toggle dark mode">dark</button>
  </div>
</header>

<div class="layout">
  <nav class="side sections" aria-label="on this page">
    <div class="track">
{sections}
    </div>
  </nav>

  <main>
    <article id="content" class="post-content">
{body}
    </article>
  </main>
{pages}
</div>

</body>
</html>
"""


# --------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------

@dataclass
class Config:
    """Settings from site.toml. Anything left out keeps the default below."""
    name: str = "Your Name"
    description: str = ""
    address: str = "example.com"
    status: str = "static"
    url: str = "https://example.com/"
    feed_url: str = ""
    feed_page: str = ""
    inline_css: bool = True
    pdf_preview: str = "viewer"
    preload_fonts: list[str] = field(default_factory=list)
    other_site: tuple[str, str] | None = None
    pages: list[tuple[str, str]] = field(default_factory=lambda: [("index", "home")])

    SIMPLE = ("name", "description", "address", "status", "url", "feed_url", "feed_page",
              "inline_css", "pdf_preview", "preload_fonts")

    @classmethod
    def load(cls, path: pathlib.Path) -> "Config":
        cfg = cls()
        data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        unknown = set(data) - set(cls.SIMPLE) - {"other_site", "pages"}
        if unknown:
            raise SystemExit(f"site.toml: unknown setting(s): {', '.join(sorted(unknown))}")
        for key in cls.SIMPLE:
            if key in data:
                setattr(cfg, key, data[key])
        if data.get("other_site"):
            cfg.other_site = (data["other_site"]["label"], data["other_site"]["url"])
        if data.get("pages"):
            cfg.pages = [(p["file"], p.get("label", p["file"])) for p in data["pages"]]
        if cfg.pdf_preview not in ("viewer", "images"):
            raise SystemExit('site.toml: pdf_preview must be "viewer" or "images"')
        if not cfg.pages or cfg.pages[0][0] != "index":
            raise SystemExit('site.toml: the first [[pages]] entry must be file = "index" (the home page)')
        return cfg


# --------------------------------------------------------------------------------------------
# HTML helpers (pure functions, covered by tests/)
# --------------------------------------------------------------------------------------------

def flatten(tokens: list[dict], max_level: int = 2):
    """Walk the table-of-contents tree, yielding headings up to max_level."""
    for t in tokens:
        if t["level"] <= max_level:
            yield t
        yield from flatten(t["children"], max_level)


def collapsible(body: str) -> str:
    """Wrap each heading (h1-h3) and what follows it in <details open>.

    A horizontal rule (---) closes every open section, so each rule-separated block stands alone.
    """
    out: list[str] = []
    stack: list[int] = []
    pos = 0
    for m in re.finditer(r'(<h([1-3]) id="[^"]*">.*?</h\2>)|(<hr ?/?>)', body, re.S):
        out.append(body[pos:m.start()])
        pos = m.end()
        if m.group(3):
            out.append("</details>\n" * len(stack))
            stack.clear()
            out.append(m.group(3))
        else:
            level = int(m.group(2))
            while stack and stack[-1] >= level:
                stack.pop()
                out.append("</details>\n")
            out.append(f"<details open>\n<summary>{m.group(1)}</summary>")
            stack.append(level)
    out.append(body[pos:])
    out.append("</details>\n" * len(stack))
    return "".join(out)


def external_links(page: str) -> str:
    """Open links to other sites and to PDFs in a new tab. mailto: and same-site pages stay put."""
    def repl(m: re.Match) -> str:
        before, href, after = m.group(1), m.group(2), m.group(3)
        if "target=" in before + after:
            return m.group(0)
        path = href.split("#")[0].split("?")[0].lower()
        if re.match(r"https?://", href) or path.endswith(".pdf"):
            return f'<a {before}href="{href}"{after} target="_blank" rel="noopener noreferrer">'
        return m.group(0)
    return re.sub(r'<a\s([^>]*?)href="([^"]*)"([^>]*)>', repl, page)


def png_size(path: pathlib.Path) -> tuple[int, int]:
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


# --------------------------------------------------------------------------------------------
# The builder
# --------------------------------------------------------------------------------------------

class Site:
    def __init__(self, root: pathlib.Path = ROOT, out: pathlib.Path | None = None,
                 clean_urls: bool = False):
        self.root = pathlib.Path(root)
        self.cfg = Config.load(self.root / "site.toml")
        self.content = self.root / "content"    # pages, written in Markdown
        self.static = self.root / "static"      # copied as-is into the output
        self.out = pathlib.Path(out) if out else self.root / "public"
        self.cache = self.root / ".cache"       # only used when pdf_preview = "images"
        self.clean_urls = clean_urls

    # -- urls ------------------------------------------------------------------------------
    def page_url(self, stem: str) -> str:
        if self.clean_urls:
            return "/" if stem == "index" else f"/{stem}"
        return f"{stem}.html"

    # -- resume preview --------------------------------------------------------------------
    def _render_pdf(self, pdf: pathlib.Path) -> list[str]:
        """Render each PDF page to .cache/preview/<name>-<n>.png. Empty list if no renderer exists."""
        out = self.cache / "preview"
        out.mkdir(parents=True, exist_ok=True)
        old = sorted(out.glob(f"{pdf.stem}-*.png"))
        if old and all(p.stat().st_mtime >= pdf.stat().st_mtime for p in old):
            return [p.name for p in old]
        for p in old:
            p.unlink()
        exe = shutil.which("pdftoppm")
        if exe:
            subprocess.run([exe, "-png", "-r", "130", str(pdf), str(out / pdf.stem)], check=True)
        else:
            try:
                import fitz  # pymupdf
            except ImportError:
                print(f"! no PDF renderer found, using the browser's viewer for {pdf.name}")
                return []
            for i, page in enumerate(fitz.open(pdf), 1):
                page.get_pixmap(dpi=130).save(out / f"{pdf.stem}-{i}.png")
        return [p.name for p in sorted(out.glob(f"{pdf.stem}-*.png"))]

    def expand_pdfs(self, body: str) -> str:
        """Turn the Markdown image ![label](file.pdf) into a collapsible preview."""
        def repl(m: re.Match) -> str:
            label, src = m.group(1), m.group(2)
            pdf = self.static / src
            pages = self._render_pdf(pdf) if self.cfg.pdf_preview == "images" and pdf.exists() else []
            if pages:
                tags = []
                for i, name in enumerate(pages, 1):
                    png = self.cache / "preview" / name
                    w, h = png_size(png)
                    data = base64.b64encode(png.read_bytes()).decode()
                    tags.append(f'<a href="{src}"><img src="data:image/png;base64,{data}" width="{w}" '
                                f'height="{h}" alt="{html.escape(pdf.name)}, page {i}"></a>')
                inner = "\n".join(tags)
            else:
                inner = (f'<object data="{src}#toolbar=0&amp;navpanes=0&amp;view=FitH" '
                         f'type="application/pdf" aria-label="{html.escape(label)}">'
                         f'<p><a href="{src}">Open {html.escape(pdf.name)}</a></p></object>')
            return (f'<details class="preview" open>\n<summary>{html.escape(label)}</summary>\n'
                    f'<div class="pdf">\n{inner}\n</div>\n</details>')
        return re.sub(r'<p><img alt="([^"]*)" src="([^"]+\.pdf)" ?/></p>', repl, body)

    # -- feed ------------------------------------------------------------------------------
    def build_feed(self) -> None:
        """Write atom.xml from content/<feed_page>.md: each '## title' with a '*YYYY-MM-DD*' line is a post."""
        stem = self.cfg.feed_page
        src = self.content / f"{stem}.md"
        if not src.exists():
            raise SystemExit(f"site.toml: feed_page '{stem}' has no content/{stem}.md")
        base = self.cfg.url.rstrip("/") + "/"
        parts = re.split(r"^## (.+)$", src.read_text(encoding="utf-8"), flags=re.M)
        entries = []
        for title, body in zip(parts[1::2], parts[2::2]):
            m = re.search(r"^\*(\d{4}-\d{2}-\d{2})\*[ \t]*$", body, re.M)
            if not m:
                continue
            body = re.sub(r"\n---\s*$", "", body.replace(m.group(0), "", 1).strip())
            content = markdown.markdown(body, extensions=["tables", "fenced_code", "sane_lists"])
            entries.append((m.group(1), title.strip(), slugify(title.strip(), "-"), content))
        entries.sort(reverse=True)
        esc = lambda x: html.escape(x, quote=True)  # noqa: E731
        updated = entries[0][0] if entries else datetime.date.today().isoformat()
        xml = ['<?xml version="1.0" encoding="utf-8"?>',
               '<feed xmlns="http://www.w3.org/2005/Atom">',
               f"  <title>{esc(self.cfg.name)}</title>",
               f'  <link href="{base}atom.xml" rel="self"/>',
               f'  <link href="{base}"/>',
               f"  <id>{base}</id>",
               f"  <updated>{updated}T00:00:00Z</updated>",
               f"  <author><name>{esc(self.cfg.name)}</name></author>"]
        for date, title, slug, content in entries:
            url = f"{urljoin(base, self.page_url(stem))}#{slug}"
            xml += ["  <entry>", f"    <title>{esc(title)}</title>", f'    <link href="{url}"/>',
                    f"    <id>{url}</id>", f"    <updated>{date}T00:00:00Z</updated>",
                    f'    <content type="html">{esc(content)}</content>', "  </entry>"]
        xml.append("</feed>")
        (self.out / "atom.xml").write_text("\n".join(xml) + "\n", encoding="utf-8")
        print(f"content/{stem}.md -> atom.xml ({len(entries)} posts)")

    # -- pages -----------------------------------------------------------------------------
    def _clean_links(self, page: str) -> str:
        """With clean URLs, turn links to this site's own pages (notes.html) into /notes."""
        stems = {stem for stem, _ in self.cfg.pages}
        def repl(m: re.Match) -> str:
            return f'href="{self.page_url(m.group(1))}{m.group(2) or ""}"' if m.group(1) in stems else m.group(0)
        return re.sub(r'href="([\w-]+)\.html(#[^"]*)?"', repl, page)

    def _page_list(self, current: str) -> str:
        cfg = self.cfg
        if len(cfg.pages) < 2 and not cfg.other_site:
            return ""
        links = [f'      <a href="{self.page_url(stem)}"'
                 + (' aria-current="page"' if stem == current else "")
                 + f">{html.escape(label)}</a>" for stem, label in cfg.pages]
        if cfg.other_site:
            label, url = cfg.other_site
            links.append(f'      <a class="ext" href="{html.escape(url)}">{html.escape(label)}</a>')
        return ('\n  <nav class="side pages" aria-label="pages">\n    <div class="track">\n'
                + "\n".join(links) + "\n    </div>\n  </nav>")

    def render_page(self, stem: str, styles: str, feed_head: str, feed_button: str) -> str:
        cfg = self.cfg
        src = self.content / f"{stem}.md"
        if not src.exists():
            raise SystemExit(f"site.toml lists page '{stem}' but content/{stem}.md does not exist")
        md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"])
        body = collapsible(self.expand_pdfs(md.convert(src.read_text(encoding="utf-8"))))
        tokens = list(flatten(md.toc_tokens))
        h1 = next((t["name"] for t in tokens if t["level"] == 1), stem)
        sections = "\n".join(f'      <a href="#{t["id"]}">{html.escape(t["name"])}</a>' for t in tokens)
        page = TEMPLATE.format(
            title=html.escape(cfg.name if stem == "index" else f"{h1} - {cfg.name}"),
            description=(f'<meta name="description" content="{html.escape(cfg.description, quote=True)}">'
                         if cfg.description else ""),
            theme_snippet=THEME_SNIPPET,
            styles=styles,
            preload="\n".join(f'<link rel="preload" href="fonts/{f}" as="font" type="font/woff2" crossorigin>'
                              for f in cfg.preload_fonts),
            # warm the cache with the other pages so switching between them is quick
            prefetch="\n".join(f'<link rel="prefetch" href="{self.page_url(s)}">'
                               for s, _ in cfg.pages if s != stem),
            feed_head=feed_head,
            home=self.page_url("index"),
            address=html.escape(cfg.address),
            status=html.escape(cfg.status),
            updated=datetime.date.today().strftime("%B %Y").lower(),
            feed_button=feed_button,
            sections=sections,
            body=body,
            pages=self._page_list(stem),
        )
        page = external_links(page)
        return self._clean_links(page) if self.clean_urls else page

    def build(self) -> None:
        cfg = self.cfg
        if self.out.exists():
            shutil.rmtree(self.out)
        shutil.copytree(self.static, self.out)

        css = (self.static / "style.css").read_text(encoding="utf-8")
        styles = f"<style>{css}</style>" if cfg.inline_css else '<link rel="stylesheet" href="style.css">'
        feed_href = cfg.feed_url or ("atom.xml" if cfg.feed_page else "")
        feed_head = (f'<link rel="alternate" type="application/atom+xml" title="{html.escape(cfg.name)}" '
                     f'href="{html.escape(feed_href)}">' if feed_href else "")
        feed_button = f'<a href="{html.escape(feed_href)}" title="Atom feed">feed</a>' if feed_href else ""

        for stem, _ in cfg.pages:
            page = self.render_page(stem, styles, feed_head, feed_button)
            (self.out / f"{stem}.html").write_text(page, encoding="utf-8")
            print(f"content/{stem}.md -> {stem}.html")
        if cfg.feed_page:
            self.build_feed()


# --------------------------------------------------------------------------------------------
# Local preview server
# --------------------------------------------------------------------------------------------

class Handler(http.server.SimpleHTTPRequestHandler):
    """Static file server that also answers /notes with notes.html, like most static hosts do."""
    def translate_path(self, path: str) -> str:
        p = super().translate_path(path)
        if not os.path.exists(p) and os.path.exists(p + ".html"):
            return p + ".html"
        return p


def serve(directory: pathlib.Path, port: int) -> None:
    handler = functools.partial(Handler, directory=str(directory))
    print(f"serving http://localhost:{port} (Ctrl-C to stop)")
    try:
        http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build the static site into public/.")
    ap.add_argument("--serve", action="store_true", help="serve public/ locally after building")
    ap.add_argument("--port", type=int, default=8000, help="port for --serve (default 8000)")
    ap.add_argument("--clean-urls", action="store_true",
                    help="use /notes instead of notes.html (also enabled by CLEAN_URLS=1)")
    args = ap.parse_args(argv)
    site = Site(clean_urls=args.clean_urls or os.environ.get("CLEAN_URLS") == "1")
    site.build()
    if args.serve:
        serve(site.out, args.port)


if __name__ == "__main__":
    main()
