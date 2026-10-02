# Markdown viewer release notes

Newest first. While building, append under **Unreleased**. On ship day, rename
that block to `## X.Y.Z — YYYY-MM-DD` and leave a fresh Unreleased section.

**Source of truth** for the running version is `VERSION` in `serve.py`. The
splash header and reader rail read it from `GET /api/state`. Do not hard-code
the version in HTML or JS.

```text
python3 serve.py --version
```

---

## Unreleased

---

## 0.2.0 — 2026-10-02

Companion reader, folder memory, and double-click desktop apps. `VERSION` is
**0.2.0**. Mac `.dmg` and Windows `.exe` ship from GitHub Actions.

### Desktop

- macOS `.dmg` and Windows `.exe` so people can double-click instead of making
  a Python venv. `packaging/build_macos.sh` / `packaging/build_windows.ps1`
  freeze `serve.py` with PyInstaller and an Md app icon.
- Frozen apps store recents in Application Support / `%APPDATA%`, open a
  browser, and show a small Open / Quit window. If 8765 is busy they try the
  next port.
- GitHub Actions: unit tests on every PR (`.github/workflows/ci.yml`); Mac and
  Windows builds on PRs and `v*` tags (`.github/workflows/desktop.yml`).

### Reader

- Folder picker lists markdown files in the current folder, not only
  subfolders. The “N md” count is files sitting in that folder. Click a `.md`
  row to open on that note. Folder names are navy; markdown names are cyan.
- Tables: headers stay at the top of the table (no longer covering the first
  body row). Body rows stripe so a wide line is easier to follow. A table that
  is still wider than the card still scrolls sideways.
- Restarting `serve.py` reopens the last folder from `config.local.json`.
- A missing `README.md` (or any `?doc=` that is not in the folder) falls back
  to the first real note instead of looking like the server is down.
- Notes rail: ▾ / ▴ per folder, **Hide all** / **Show all**, bolder white
  folder names, draggable width, hover previews to the right of the list.
- Filter notes uses fuzzysort (CDN): fuzzy match, gold-on-navy highlights,
  non-matches actually leave the list.
- Splash **This computer** shortcuts include Downloads.
- Settings gear (Viewer / Models / Run). Models follows Zeus Hub Config plus
  `ai/providers.json`. Run prompts live in `ai/prompts/*.json`. Keys stay in
  `config.local.json` and are redacted on GET.
- Header **AI** toggle left of Folders. Outline = off; filled cyan = on.

### Companion and memory

- Opening a note writes `_memory.json` at the folder root (SHA-256, headings,
  local links, keyphrases). YAKE ranks multi-word phrases; one-word terms stay
  out, and counts of 1–2 are dropped. Stopwords live in `ai/stopwords.txt`.
- Opening a subfolder reuses an ancestor `_memory.json` via `{ "ref": ".." }`
  instead of a second store.
- When AI is on: TL;DR / Important idea / Next action. First fill bounces then
  types in; later opens show the cached pack at once. Action buttons (Outline,
  Proofread, Summarize, Tighten) are outlined cyan rectangles, not keyword
  pills. Keyword chips are navy; pressed chips highlight the note in a fixed
  14-color palette.
- Ask is a chat thread (user right, model left) with markdown replies, a
  regenerate control, copy, pencil-edit, and Copy chat. Ask… becomes Close
  while the thread is open. Threads live in `_chats/<note>.jsonl`. Highlight →
  Copy / AI Insights. Settings → Run stays the save-to-file path.

### Tests

- `tests/` holds stdlib unit tests for `serve.py` and Playwright tests for the
  reader (splash listing, table header vs first row, keyword chips, Ask
  edit/retry, companion wait-then-stream).

---

## 0.1.0 — 2026-09-30

First numbered release. `VERSION` is **0.1.0**.

### New

- Local folder reader: stdlib `serve.py` (Python 3.9+, no pip). GitHub-flavored
  markdown, tables, `mermaid` fences, and KaTeX `\(…\)` / `\[…\]` (dollar signs
  stay money). Pictures, video, and PDFs open in a lightbox; `thumbs/` paths
  open the full-size file next to them.
- Extra MIME types for images, video, audio, PDF, CSV, JSON, YAML, and the rest.
  Every external `http(s)` link is treated the same: new tab, arrow, host chip
  (chips are hidden in tables).
- Chrome: cool-gray canvas, white shadowed cards, dark navy rail, cyan CTAs,
  Inter.
- Fluid article: left/right gutter from `config.json` (`gutter`, default
  `1.75rem`; `1rem` on a phone) and no max-width. Widen the window and tables
  grow with it. A table that is still wider than the card scrolls on its own.
- Reading tools: text size (A− / A+), **Wide** (`W`) to hide the notes rail,
  note filter (`/`), on-this-page heading list, copy on code fences, `[` / `]`
  previous / next note, Top after you scroll, print hides the chrome.
- Hover previews (fine pointer): local notes and sections as text cards, local
  pictures in the card, external pages via `/api/preview?url=` (title,
  description, og image; public hosts only; no private or localhost; skip
  icon/favicon banners).
- Portable `config.json` (host, port, start directory, shortcuts, gutter,
  skip-dirs). Recent folders and last path live in gitignored
  `config.local.json`. Startup is `python3 serve.py` with an optional folder
  argument; otherwise `index.html` is a splash folder picker. The reader is
  `viewer.html` with a Folders link back to the splash. Folder browse
  (`/api/fs`) and open (`POST /api/open`) are localhost-only.
- Versioning: `VERSION` in `serve.py`, boot log, `--version`, `/api/state`,
  splash header, and reader rail.

### Notes

- Marked, Mermaid, and KaTeX load from a CDN, so the first load needs network.
- Opening `index.html` as a file will not work; a local server is required.
