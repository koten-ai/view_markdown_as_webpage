# View markdown as a webpage

A small local reader for a folder of notes. GitHub is fine for editing. This is for **reading**: larger type, click a figure to enlarge, and tell a local note from an external page.

HTML/CSS/JS have no build step. Keyword ranking uses [YAKE](https://github.com/LIAAD/yake) from `requirements.txt` (a venv). Without that package the reader still runs and falls back to phrase counts.

## Desktop app (no terminal)

Download a Mac `.dmg` or Windows `.exe` from
[Releases](https://github.com/koten-ai/view_markdown_as_webpage/releases).
Build recipes live under [`packaging/`](packaging/README.md). Double-click
**Markdown Viewer** — it starts the local server, opens a browser, and keeps a
small Open / Quit window.

```bash
bash packaging/build_macos.sh          # writes dist/*.dmg
# Windows PowerShell:  ./packaging/build_windows.ps1
```

macOS: drag the app to Applications. The first open may need right-click → Open (the build is not signed). Windows: run the `.exe`; SmartScreen may ask for **More info** → **Run anyway**. Recents stay in Application Support / `%APPDATA%`, not inside the app bundle.

## Run from source

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python serve.py
```

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765). The splash page lets you browse this computer. Each folder row shows how many markdown files sit in that folder; after you open the folder, the list shows those files plus any subfolders. Folder names are navy; markdown names are cyan. Click **View this folder**, or click a `.md` row to open on that note. Recent folders are remembered. A local server is required; opening `index.html` as a file will not work.

You can still pass a folder on the command line (it becomes the first “recent” entry):

```bash
.venv/bin/python serve.py /path/to/your/notes
```

```text
.venv/bin/python serve.py [folder] [--port 8765] [--host 127.0.0.1] [--title Name] [--version]
```

| Flag | Meaning |
|---|---|
| `folder` | Optional. If omitted, pick a folder in the browser |
| `--port` | Overrides `config.json` (default `8765`) |
| `--host` | Overrides `config.json` (default `127.0.0.1`) |
| `--title` | Header name (default: folder name) |
| `--browser` | Open a web browser (the `.app` / `.exe` always do this) |
| `--no-gui` | Skip the small desktop status window |
| `--version` | Print the running version and exit |

Host, port, start directory, shortcuts, and skip-list live in [`config.json`](config.json). Default shortcut chips are Home, Documents, Desktop, and Downloads. Recent folders are stored in `config.local.json` (gitignored) so the committed config stays portable. The last folder is reopened when the server starts; the splash page still lets you switch.

## What you get

| In the viewer | Meaning |
|---|---|
| Cyan link | Another note (`.md`, `.markdown`, …) — stays in the viewer |
| Green link + type | Local file (`png`, `pdf`, `mp4`, …). Pictures, video, and PDFs open in a lightbox. |
| Arrow ↗ + host | Any external site (Grokipedia, Jira, GitHub, …) — new tab. Host chips are hidden in tables. |
| Click a picture | Lightbox; Esc or the dim area closes it. Paths under `thumbs/` open the full-size file next to them. |
| **A−** / **A+** | Text size (kept in the browser) |
| **Wide** | Hide the notes rail so the article (and tables) use the extra width. `W` does the same. Kept in the browser. |
| Drag the rail edge | Widen or narrow the notes list. Kept in the browser. Hidden on a phone (the list is an overlay there). |
| **AI** (left of Folders) | Outline chip = off; filled cyan with twinkling stars = on. Kept in the browser. Run is disabled while this is off. When on, the companion strip fills in the background: TL;DR / Important idea / Next action (left to right). The first time a note is filled, those three cards bounce then type the pack in; after that they appear at once, like the rest of the page. Plus **action buttons from `ai/prompts/*.json`** (Summarize, Tighten, …) and Ask…. Action buttons are outlined cyan rounded rectangles so they do not look like keyword pills. The strip uses a cyan wash so it is not the note card. Ask is a chat thread (you on the right, the model on the left). The chip reads **Close** while the thread is open. A pencil to the left of your bubbles lets you edit a question and ask again (later turns after that question are dropped). Replies are markdown: local note links, images, and hyperlinks work in the bubbles. Copy chat copies the thread. Each assistant turn has a regenerate control (circle with an arrow) and a copy icon. Chats persist in `_chats/<note>.jsonl` even if the note file changes (the next turn attaches the new file once). The full note is sent on the first turn or after a hash change, not on every follow-up. |
| Keywords / `_memory.json` | Opening a note writes `_memory.json` at the notes root (hash, headings, local links, keyphrases). If you later open a subfolder, that folder writes `{ "ref": ".." }` and reuses the parent file instead of a second store. YAKE ranks **multi-word** phrases; singles stay out of the top list, and counts of 1–2 are dropped. No model required. Click a keyword chip to highlight that phrase in the note (each phrase has a fixed color from a small palette); click again to clear. Underscore files are hidden in the splash picker. |
| Gear (bottom of the rail) | Settings lightbox. **Viewer** is `config.json` plus this-browser reading prefs. **Models** is Hub-style AI providers (the same vendor list as Zeus Hub Config). **Run** sends the open note through a saved prompt from `ai/prompts/*.json`. Keys stay in gitignored `config.local.json`. |
| Folder name | Bold white label. The ▾ / ▴ button to its left hides or shows that folder. |
| **Hide all** / **Show all** | Collapse or expand every folder group. |
| Filter | Type in the rail, or press `/`. [fuzzysort](https://github.com/farzher/fuzzysort) fuzzy-matches titles and paths and highlights the letters. Enter opens the first match. |
| On this page | Jump list of headings on longer notes |
| Copy | Button on code fences. Highlight in the note also opens a small menu: **Copy** and **AI Insights**. |
| Highlight → AI Insights | Quote the selection, type a question, or use **Explain more** / **Simplify**. Sends into the Ask chat with the selected passage. Needs AI on. |
| `[` / `]` | Previous / next note |
| Top | Appears after you scroll; print hides the chrome |
| Hover a link | Preview card. In the notes rail the card sits to the **right** of the list so you can move the mouse down the sidebar. In the article it still opens under the link. Local notes show the heading and a slice of the text; local pictures show the image; external pages show the title and description (sites usually block a live iframe). |

The article is **fluid**: a left/right gutter from `config.json` (`gutter`, default 1.75rem; 1rem on a phone) and no max-width. Widen the window and tables grow with it instead of clipping. If a table is still wider than the card, that table scrolls sideways on its own. Table headers stay at the top of the table so the first body row is not covered. Body rows alternate a light gray so a wide row is easier to follow.

Images: PNG, JPEG, GIF, WebP, AVIF, SVG, BMP, TIFF, HEIC, ICO.  
Also inline: MP4 / WebM / MOV, audio, PDF. The server sends the usual MIME types for those plus CSV, JSON, YAML, and the rest.

Also: GitHub-flavored markdown, tables, `mermaid` fences, and KaTeX `\(…\)` / `\[…\]` (dollar signs are left alone so `$300` stays money). Note filter uses `fuzzysort` from a CDN.

The sidebar lists every markdown file it finds. Root files sit under the folder name; files in a subfolder are grouped by that folder. `README.md` opens first when it exists.

## How it works

`serve.py` is a tiny HTTP server (stdlib plus optional YAKE).

- `/` — splash page (pick a folder)
- `/viewer.html`, `/viewer.css`, `/viewer.js` — the reader
- `/api/state`, `/api/fs`, `/api/open` — folder picker (localhost only)
- `/api/notes` — JSON list of markdown in the open folder
- `/api/preview?url=` — title/description for an external http(s) page (public hosts only; used on hover)
- `/api/config`, `/api/ai`, `/api/ai/test`, `/api/ai/models`, `/api/ai/run`, `/api/ai/save` — settings and AI (localhost only). Keys are never returned in full; an empty/`..........` key on save keeps the stored one. Vendor list is `ai/providers.json`. Run prompts are `ai/prompts/*.json` (`{{note}}`, optional `{{prompt}}`).
- `/api/memory`, `/api/memory/visit`, `/api/memory/enrich` — folder memory in `_memory.json` (localhost only). Visit ranks keyphrases with YAKE (stopwords in `ai/stopwords.txt`; phrases only, count ≥ 3). Enrich fills the three cards when AI is on and the file hash changed.
- `/api/chat`, `/api/chat/retry`, `/api/chat/edit` — per-note Ask thread in `_chats/<note>.jsonl` (localhost only). The full note is attached once per hash; later turns send the thread plus a short briefing. Edit replaces a user question and truncates the thread after it.
- everything else — that folder (notes, images, video, PDFs, …)

`.git`, virtualenvs, and `node_modules` are not served.

## Version

Single source of truth: `VERSION` in [`serve.py`](serve.py). That value is
wired into the boot log, `python3 serve.py --version`, `GET /api/state`, the
splash header, and the reader rail. Do not hard-code it in HTML or JS.

What shipped in each number lives in [`RELEASE_NOTES.md`](RELEASE_NOTES.md)
(newest first; keep an **Unreleased** section while building). To cut a
release: bump `VERSION`, move Unreleased into a dated `## X.Y.Z` block, restart
the server, then tag `vX.Y.Z`. GitHub Actions builds the `.dmg` and `.exe` on
that tag; attach them on
[Releases](https://github.com/koten-ai/view_markdown_as_webpage/releases).

## Requirements

Python 3.9+ on the machine that opens the browser. Keywords want the venv
packages in [`requirements.txt`](requirements.txt). Marked, Mermaid, and KaTeX
load from a CDN, so the reader needs network the first time those caches fill.

## Tests

Unit tests cover `serve.py` (including YAKE when it is installed). Playwright
needs the extra packages in [`tests/requirements.txt`](tests/requirements.txt).

```bash
.venv/bin/python -m unittest discover -s tests
python3 -m venv tests/.venv
tests/.venv/bin/pip install -r tests/requirements.txt
tests/.venv/bin/playwright install chromium
tests/.venv/bin/python -m unittest discover -s tests
```

See [`tests/README.md`](tests/README.md).

Apache License 2.0 (see [LICENSE](LICENSE)).
