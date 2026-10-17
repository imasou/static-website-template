# Minimal static site

A small, fast personal site you write in Markdown. A single Python script turns your pages into
plain HTML, and the result can be hosted on any static host. There are no frameworks, no trackers
and no third-party requests.

**Features**

- Pages written in Markdown, built to static HTML by `build.py`
- Dark and light themes with a toggle (the choice stays in the visitor's browser)
- Every section collapses, and a floating list on the left tracks where you are on the page
- A second floating list on the right for the site's pages, plus an optional link to another site
- On phones and narrow windows both lists become slim rows pinned under the top bar, so they stay
  reachable while you scroll; swipe a row sideways to see the rest, and the row follows your reading.
  They slide up out of the way while you scroll down and slide back as soon as you scroll up
- PDF preview for a resume or any other document: the browser's viewer on desktop, page images on
  phones (rendered at build time)
- Optional Atom feed button (point it at another site's feed, or build one from a page)
- Soft fade between pages, honouring the visitor's "reduce motion" setting
- Works without JavaScript (the toggle, highlights and fades are progressive enhancements) and
  with browsers' reader modes
- Fonts are bundled, so nothing is loaded from other servers

## Quick start

```sh
pip install -r requirements.txt
python3 build.py --serve       # builds into public/ and serves http://localhost:8000
```

Edit `site.toml` and the files in `content/`, rebuild, and refresh. Preview over `http://` rather
than by opening the HTML files directly: browsers treat `file://` pages as separate sites, so page
changes can flash and caching does not work.

## Project layout

```
site.toml          settings (name, address, pages, feed, ...)
content/           your pages, in Markdown (index.md is the home page)
static/            copied as-is into the site
  style.css        all styling (copied into each page by the build)
  site.js          optional JavaScript
  resume.pdf       placeholder document; replace it
  fonts/           bundled fonts, with their licences
  _headers         response headers for Cloudflare Pages and Netlify
build.py           the builder
tests/             unit tests for the builder
public/            generated output (git-ignored)
```

## Configuration

Everything lives in `site.toml`. Anything you leave out keeps its default.

| setting | meaning |
| --- | --- |
| `name` | used in page titles and the feed |
| `description` | meta description for search results and link previews |
| `address` | the large text in the top bar; it links to the home page |
| `status` | text beside the address, followed by the build month and year |
| `url` | public address of the site; only used by the local feed |
| `feed_url` | where the `feed` button points, e.g. another site's feed. Empty hides it |
| `feed_page` | build a local `atom.xml` from this page in `content/` (see "Feed") |
| `inline_css` | copy `style.css` into every page (fewer requests, no unstyled flash) |
| `pdf_preview` | `"viewer"` (browser's PDF viewer on desktop, page images on narrow screens) or `"images"` (page images everywhere, embedded in the HTML) |
| `preload_fonts` | font files in `static/fonts/` used above the fold, fetched early |
| `[other_site]` | optional link at the end of the page list: `label` and `url` |
| `[[pages]]` | the pages, in order: `file` (matches `content/<file>.md`) and `label`. The first must be `index` |

## Writing content

Pages are ordinary Markdown with a few conventions the theme builds on:

| you write | you get |
| --- | --- |
| `# title` | the page heading, and the first entry in the left-hand list |
| `## section` | a collapsible section, and an entry in the left-hand list |
| `### subsection` | a collapsible section inside its parent |
| `---` | a horizontal rule; it also ends every open section |
| `> text` | a blockquote with a bar down the side |
| `![label](file.pdf)` | a collapsible preview of `static/file.pdf` |
| `[text](https://...)` | a link that opens in a new tab (same for links to PDFs) |
| `[text](other.html)` | a link to another page of the site |

Tables, fenced code blocks and ordered or unordered lists work as usual. Links to other pages are
written as `name.html`; with `--clean-urls` they are rewritten to `/name` automatically.

**Adding a page:** create `content/foo.md` starting with `# foo`, then add a
`[[pages]]` entry with `file = "foo"` to `site.toml`.

**Reader mode:** browsers only offer reader mode on pages with a decent amount of paragraph text,
so very short pages may not trigger it.

## Feed

The `feed` button is hidden unless you set one of these:

- `feed_url = "https://other-site.example/atom.xml"` points at a feed that lives elsewhere, such
  as a blog on its own subdomain. Nothing is generated here.
- `feed_page = "notes"` builds `atom.xml` from `content/notes.md`. Each `## title` section that has
  a `*YYYY-MM-DD*` line under its heading becomes a post. Set `url` to the site's public address so
  the entry links are absolute.

## Customising

- **Colours, sizes, fonts:** the top of `static/style.css` defines CSS variables (`--bg`, `--fg`,
  `--muted`, `--rule`, `--bar-h`, `--mono`, `--display`, ...) for the dark theme, with the light theme
  overriding them under `html[data-theme="light"]`.
- **Changing fonts:** put the `.woff2` files in `static/fonts/`, update the `@font-face` rules at the
  top of `style.css`, and update `preload_fonts` in `site.toml`. Keep each font's licence file beside it.
- **Markup:** the page skeleton is the `TEMPLATE` string at the top of `build.py`.
- **Behaviour:** `static/site.js` holds the theme toggle, the section highlight, the springy side
  lists and the page fade. Delete the file (and its `<script>` tag in the template) if you want a
  JavaScript-free site; everything else keeps working.

## Building

```sh
python3 build.py                 # build into public/
python3 build.py --clean-urls    # links like /notes instead of notes.html (or set CLEAN_URLS=1)
python3 build.py --serve         # build, then serve public/ on http://localhost:8000
python3 build.py --serve --port 9000
```

Clean URLs use absolute paths (`/notes`), so use them only when the site is served from the root of
its own domain or subdomain. The default `notes.html` links are relative and work anywhere,
including in a subfolder.

The phone fallback (and `"images"` mode) needs the PDF in `static/` and a renderer: `pymupdf` is in `requirements.txt`, so `pip install -r requirements.txt` is enough (poppler's
`pdftoppm` is used instead if it is installed). If the PDF or a renderer is missing, the build keeps only the
browser's viewer (and prints a warning), which does not work on most phones.

## Deploying

The output is plain files in `public/`, so any static host works. The build runs in Python 3.9+
(Python 3.11+ needs nothing extra; older versions install `tomli` from `requirements.txt`).

### Cloudflare Pages

Connect the repository (Workers & Pages, Create, Pages, Connect to Git), then:

| setting | value |
| --- | --- |
| Framework preset | None |
| Build command | `pip install -r requirements.txt && python3 build.py --clean-urls` |
| Build output directory | `public` |

`.python-version` pins Python 3.12. Add your domain or subdomain under **Custom domains**.
`static/_headers` is applied automatically (see below).

### Netlify

Same build command and publish directory (`public`). `_headers` is supported too.

### GitHub Pages

Pages cannot run the build for you from a branch, so either run the build in a GitHub Actions
workflow that publishes `public/`, or build locally and publish the contents of `public/`. `_headers`
is ignored there. Leave `--clean-urls` off if the site lives at `username.github.io/repo/`.

### Anywhere else

Run the build and upload `public/`.

### Response headers

`static/_headers` sets a few conservative headers: no referrer, no MIME sniffing, framing only by the
same origin (this keeps the PDF preview working), and long caching for fonts. It is only used by
hosts that understand the `_headers` format. Equivalent settings can be made in any web server.

## Tests and CI

```sh
python3 -m unittest discover -s tests -v
```

The tests build small throwaway sites and check the builder's output (links, sections, clean URLs,
feed, configuration errors). `.github/workflows/ci.yml` runs them and a full build on every push.
`static/site.js` has no automated tests; try it in a browser after changing it.

## How it works

`build.py` reads `site.toml`, converts each Markdown file with
[Python-Markdown](https://python-markdown.github.io/), wraps headings in `<details>` elements so they
collapse, builds the left-hand list from the headings, fills the template, and copies `static/`
alongside the pages. Collapsing uses native `<details>`, so it needs no script. The script adds
only what HTML and CSS cannot: the theme toggle, the highlight that follows your scrolling, the
bounce on the lists, and the fade when leaving a page.

## Browser notes

- Everything is progressive: without JavaScript you lose the toggle, highlights and bounce, not content.
- Visitors with "reduce motion" enabled get no fades or bounce.
- With `pdf_preview = "viewer"`, screens up to 64rem wide get the page images (tap one to open the PDF) and wider
  screens get the browser's viewer. Keep the `download` link above it as a fallback.

## Privacy

The site makes no requests to third parties. Fonts are served from the same origin. The only thing
stored in the visitor's browser is the light/dark choice, in `localStorage`. External links open
with `noopener noreferrer`.

## Troubleshooting

- **A page flashes white when switching pages:** serve over `http://` (`--serve`) instead of opening
  files directly, and prefer a real host, which caches pages and fonts.
- **`/notes` gives "not found" on a host:** the host does not map extensionless URLs. Build without
  `--clean-urls`.
- **The resume preview is blank (especially on a phone):** check that
  `static/resume.pdf` exists and the Markdown refers to it by that file name, and look for a
  `no PDF renderer found` line in the build output.
- **Fonts show in a fallback face:** the files in `static/fonts/` must match the names in
  `style.css` and `preload_fonts`.

## Licences and credits

- Add a `LICENSE` file to state the terms for the code and content in your copy of this repository.
- Fonts in `static/fonts/` are [IM Fell English](https://fonts.google.com/specimen/IM+Fell+English)
  and [JetBrains Mono](https://www.jetbrains.com/lp/mono/), both under the SIL Open Font License 1.1.
  Their licence texts sit beside the font files and must stay with them.
- Markdown conversion uses [Python-Markdown](https://python-markdown.github.io/) (BSD licence).
