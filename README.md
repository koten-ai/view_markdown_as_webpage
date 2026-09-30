# View markdown as a webpage

A small local reader for a folder of notes. GitHub is fine for editing. This is for **reading**: larger type, click a figure to enlarge, and tell a local note from an external page.

Stdlib Python only. No `pip`, no build step. The HTML/CSS/JS live in this repo; the notes and images come from the folder you pick.

## Run

```bash
python3 serve.py
```

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765). The splash page lets you browse this computer and click **View this folder**. Recent folders are remembered. A local server is required; opening `index.html` as a file will not work.

You can still pass a folder on the command line (it becomes the first “recent” entry):

```bash
python3 serve.py /path/to/your/notes
```

```text
python3 serve.py [folder] [--port 8765] [--host 127.0.0.1] [--title Name] [--version]
```

| Flag | Meaning |
|---|---|
| `folder` | Optional. If omitted, pick a folder in the browser |
| `--port` | Overrides `config.json` (default `8765`) |
| `--host` | Overrides `config.json` (default `127.0.0.1`) |
| `--title` | Header name (default: folder name) |
| `--version` | Print the running version and exit |

Host, port, start directory, shortcuts, and skip-list live in [`config.json`](config.json). Recent folders are stored in `config.local.json` (gitignored) so the committed config stays portable. The last folder is reopened when the server starts; the splash page still lets you switch.

## What you get

| In the viewer | Meaning |
|---|---|
| Cyan link | Another note (`.md`, `.markdown`, …) — stays in the viewer |
| Green link + type | Local file (`png`, `pdf`, `mp4`, …). Pictures, video, and PDFs open in a lightbox. |
| Arrow ↗ + host | Any external site (Grokipedia, Jira, GitHub, …) — new tab. Host chips are hidden in tables. |
| Click a picture | Lightbox; Esc or the dim area closes it. Paths under `thumbs/` open the full-size file next to them. |
| **A−** / **A+** | Text size (kept in the browser) |
| **Wide** | Hide the notes rail so the article (and tables) use the extra width. `W` does the same. Kept in the browser. |
| Filter | Type in the rail, or press `/`. Enter opens the first match. |
| On this page | Jump list of headings on longer notes |
| Copy | Button on code fences |
| `[` / `]` | Previous / next note |
| Top | Appears after you scroll; print hides the chrome |
| Hover a link | Preview card. Local notes show the heading and a slice of the text; local pictures show the image; external pages show the title and description (sites usually block a live iframe). |

The article is **fluid**: a left/right gutter from `config.json` (`gutter`, default 1.75rem; 1rem on a phone) and no max-width. Widen the window and tables grow with it instead of clipping. If a table is still wider than the card, that table scrolls sideways on its own.

Images: PNG, JPEG, GIF, WebP, AVIF, SVG, BMP, TIFF, HEIC, ICO.  
Also inline: MP4 / WebM / MOV, audio, PDF. The server sends the usual MIME types for those plus CSV, JSON, YAML, and the rest.

Also: GitHub-flavored markdown, tables, `mermaid` fences, and KaTeX `\(…\)` / `\[…\]` (dollar signs are left alone so `$300` stays money).

The sidebar lists every markdown file it finds. Root files sit under the folder name; files in a subfolder are grouped by that folder. `README.md` opens first when it exists.

## How it works

`serve.py` is a tiny stdlib HTTP server.

- `/` — splash page (pick a folder)
- `/viewer.html`, `/viewer.css`, `/viewer.js` — the reader
- `/api/state`, `/api/fs`, `/api/open` — folder picker (localhost only)
- `/api/notes` — JSON list of markdown in the open folder
- `/api/preview?url=` — title/description for an external http(s) page (public hosts only; used on hover)
- everything else — that folder (notes, images, video, PDFs, …)

`.git`, virtualenvs, and `node_modules` are not served.

## Version

Single source of truth: `VERSION` in [`serve.py`](serve.py). That value is
wired into the boot log, `python3 serve.py --version`, `GET /api/state`, the
splash header, and the reader rail. Do not hard-code it in HTML or JS.

What shipped in each number lives in [`RELEASE_NOTES.md`](RELEASE_NOTES.md)
(newest first; keep an **Unreleased** section while building). To cut a
release: bump `VERSION`, move Unreleased into a dated `## X.Y.Z` block, restart
the server, then tag `vX.Y.Z`.

## Requirements

Python 3.9+ on the machine that opens the browser. Marked, Mermaid, and KaTeX load from a CDN, so the reader needs network the first time those caches fill.

Apache License 2.0 (see [LICENSE](LICENSE)).
