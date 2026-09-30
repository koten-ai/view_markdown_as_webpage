# View markdown as a webpage

A small local reader for a folder of notes. GitHub is fine for editing. This is for **reading**: larger type, click a figure to enlarge, and tell a local note from an external page.

Stdlib Python only. No `pip`, no build step. The HTML/CSS/JS live in this repo; the notes and images come from the folder you point at.

## Run

From this repo, pass any notes folder:

```bash
python3 serve.py /path/to/your/notes
```

Or from inside the notes folder, call this script:

```bash
python3 /path/to/view_markdown_as_webpage/serve.py
```

If this clone sits next to the notes (same parent directory):

```bash
python3 ../view_markdown_as_webpage/serve.py
```

Then open [http://127.0.0.1:8765](http://127.0.0.1:8765). A local server is required so the page can load the other notes, images, and files. Opening `index.html` as a file will not work.

```text
python3 serve.py [folder] [--port 8765] [--host 127.0.0.1] [--title Name]
```

| Flag | Meaning |
|---|---|
| `folder` | Directory of markdown (default: current directory) |
| `--port` | Port (default `8765`) |
| `--host` | Bind address (default `127.0.0.1`) |
| `--title` | Header name (default: folder name) |

Example — graph research notes, cloned next to this repo:

```bash
python3 serve.py ../graph_research
```

## What you get

| In the viewer | Meaning |
|---|---|
| Cyan link | Another note (`.md`, `.markdown`, …) — stays in the viewer |
| Green link + type | Local file (`png`, `pdf`, `mp4`, …). Pictures, video, and PDFs open in a lightbox. |
| Arrow ↗ + host | Any external site (Grokipedia, Jira, GitHub, …) — new tab. Host chips are hidden in tables. |
| Click a picture | Lightbox; Esc or the dim area closes it. Paths under `thumbs/` open the full-size file next to them. |
| **A−** / **A+** | Text size (kept in the browser) |

Images: PNG, JPEG, GIF, WebP, AVIF, SVG, BMP, TIFF, HEIC, ICO.  
Also inline: MP4 / WebM / MOV, audio, PDF. The server sends the usual MIME types for those plus CSV, JSON, YAML, and the rest.

Also: GitHub-flavored markdown, tables, `mermaid` fences, and KaTeX `\(…\)` / `\[…\]` (dollar signs are left alone so `$300` stays money).

The sidebar lists every markdown file it finds. Root files sit under the folder name; files in a subfolder are grouped by that folder. `README.md` opens first when it exists.

## How it works

`serve.py` is a tiny stdlib HTTP server.

- `/`, `/viewer.css`, `/viewer.js` — this repo (the reader)
- `/api/notes` — JSON list of markdown under the folder you passed
- everything else — that folder (notes, images, video, PDFs, …)

`.git`, virtualenvs, and `node_modules` are not served.

## Requirements

Python 3.9+ on the machine that opens the browser. Marked, Mermaid, and KaTeX load from a CDN, so the reader needs network the first time those caches fill.

Apache License 2.0 (see [LICENSE](LICENSE)).
