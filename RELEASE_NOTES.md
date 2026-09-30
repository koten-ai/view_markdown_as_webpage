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

-

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
