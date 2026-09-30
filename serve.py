#!/usr/bin/env python3
"""Local markdown viewer. Stdlib only — no pip.

Point it at any folder of notes. The HTML/CSS/JS live next to this
script; markdown, images, and other files come from the folder you pass.

    python3 serve.py
    python3 serve.py /path/to/notes
    python3 serve.py ../graph_research --port 8765

Then open http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

APP_DIR = Path(__file__).resolve().parent
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    ".idea",
    ".vscode",
    ".grok",
}
APP_PATHS = {"/", "/index.html", "/viewer.css", "/viewer.js"}
NO_CACHE_EXT = {
    ".html",
    ".css",
    ".js",
    ".md",
    ".markdown",
    ".mdown",
    ".mkd",
    ".json",
    ".svg",
    ".txt",
    ".csv",
    ".yml",
    ".yaml",
}
README_NAMES = (
    "README.md",
    "Readme.md",
    "readme.md",
    "README.markdown",
    "readme.markdown",
)
MD_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
EXTRA_MIME = {
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".mdown": "text/markdown; charset=utf-8",
    ".mkd": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".yaml": "text/yaml; charset=utf-8",
    ".yml": "text/yaml; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".ico": "image/x-icon",
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".pdf": "application/pdf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}

for _ext, _mime in EXTRA_MIME.items():
    mimetypes.add_type(_mime, _ext)


def first_heading(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:40]:
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return ""


def group_for(rel: str, folder_name: str) -> str:
    if "/" not in rel:
        return folder_name
    return rel.split("/", 1)[0]


def sort_key(item: dict, folder_name: str) -> tuple:
    path = item["path"]
    name = path.rsplit("/", 1)[-1]
    group = item["group"]
    g = (0, group.lower()) if group == folder_name else (1, group.lower())
    lower = name.lower()
    if lower == "readme.md":
        return g + (0, "")
    if lower == "glossary.md":
        return g + (1, "")
    return g + (2, path.lower())


def list_notes(root: Path, folder_name: str) -> list[dict]:
    notes: list[dict] = []
    seen: set[str] = set()
    for suffix in MD_SUFFIXES:
        for path in root.rglob("*" + suffix):
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            posix = rel.as_posix()
            if posix in seen:
                continue
            seen.add(posix)
            notes.append(
                {
                    "path": posix,
                    "title": first_heading(path) or path.stem,
                    "group": group_for(posix, folder_name),
                }
            )
    notes.sort(key=lambda n: sort_key(n, folder_name))
    return notes


def default_doc(notes: list[dict]) -> str:
    names = {n["path"]: n for n in notes}
    for candidate in README_NAMES:
        if candidate in names:
            return candidate
    return notes[0]["path"] if notes else ""


def is_safe(root: Path, rel: Path) -> bool:
    try:
        resolved = (root / rel).resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    try:
        parts = resolved.relative_to(root.resolve()).parts
    except ValueError:
        return False
    return not any(part in SKIP_DIRS for part in parts)


def make_handler(app_dir: Path, notes_dir: Path, title: str):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(notes_dir), **kwargs)

        def end_headers(self) -> None:
            path = urlparse(self.path).path
            ext = Path(unquote(path)).suffix.lower()
            if ext in NO_CACHE_EXT or path in APP_PATHS or path == "/api/notes":
                self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def guess_type(self, path: str):
            ext = Path(path).suffix.lower()
            if ext in EXTRA_MIME:
                return EXTRA_MIME[ext]
            return super().guess_type(path)

        def translate_path(self, path: str) -> str:
            bare = unquote(path.split("?", 1)[0].split("#", 1)[0])
            if bare in ("/", "/index.html", ""):
                return str(app_dir / "index.html")
            if bare in ("/viewer.css", "/viewer.js"):
                return str(app_dir / bare.lstrip("/"))
            return super().translate_path(path)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/notes":
                notes = list_notes(notes_dir, title)
                body = json.dumps(
                    {
                        "title": title,
                        "defaultDoc": default_doc(notes),
                        "notes": notes,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            rel = Path(unquote(parsed.path.lstrip("/")))
            if parsed.path not in APP_PATHS and parsed.path not in ("",):
                if not is_safe(notes_dir, rel):
                    self.send_error(404, "Not found")
                    return
            super().do_GET()

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("%s — %s\n" % (self.address_string(), fmt % args))

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve a folder of markdown files as a local webpage."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Folder of .md files to view (default: current directory)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--title",
        default=None,
        help="Name in the header (default: folder name)",
    )
    args = parser.parse_args()

    notes_dir = Path(args.root).expanduser().resolve()
    if not notes_dir.is_dir():
        print("not a folder: %s" % notes_dir, file=sys.stderr)
        return 2

    title = args.title or notes_dir.name
    handler = make_handler(APP_DIR, notes_dir, title)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    url = "http://%s:%s" % (args.host, args.port)
    print("Markdown viewer", flush=True)
    print("  folder  %s" % notes_dir, flush=True)
    print("  %s" % url, flush=True)
    print("  Ctrl-C to stop", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
