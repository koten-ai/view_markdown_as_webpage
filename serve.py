#!/usr/bin/env python3
"""Local markdown viewer. Stdlib only — no pip.

    python3 serve.py
    python3 serve.py /path/to/notes
    python3 serve.py --version

Open http://127.0.0.1:8765 and pick a folder on the splash page.
Host/port/start directory live in config.json next to this script.
"""
from __future__ import annotations

import argparse
import html as htmlmod
import ipaddress
import json
import mimetypes
import socket
import sys
import threading
import time
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

# Single source of truth for:
#   python3 serve.py --version
#   startup log
#   GET /api/state → version  (splash header + reader rail; never hard-code in HTML/JS)
#
# Bump here, then move Unreleased in RELEASE_NOTES.md and tag vX.Y.Z.
# Current: 0.1.0 — first numbered release (folder reader, splash picker, reading tools).
VERSION = "0.1.0"

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
APP_PATHS = {
    "/",
    "/index.html",
    "/viewer.html",
    "/viewer.css",
    "/viewer.js",
    "/splash.js",
}
CONFIG_PATH = APP_DIR / "config.json"
LOCAL_PATH = APP_DIR / "config.local.json"
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8765,
    "title": None,
    "start_dir": "~",
    "recent_max": 8,
    "gutter": "1.75rem",
    "shortcuts": ["~", "~/Documents", "~/Desktop"],
    "skip_dirs": sorted(SKIP_DIRS),
    "recent": [],
    "last": "",
}
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


def list_notes(root: Path, folder_name: str, skip: set[str] | None = None) -> list[dict]:
    skip_dirs = skip if skip is not None else SKIP_DIRS
    notes: list[dict] = []
    seen: set[str] = set()
    for suffix in MD_SUFFIXES:
        for path in root.rglob("*" + suffix):
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if any(part in skip_dirs for part in rel.parts):
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


PREVIEW_MAX_BYTES = 65536
PREVIEW_TIMEOUT = 4
PREVIEW_TTL = 600.0
_PREVIEW_CACHE: dict[str, tuple[float, dict]] = {}


class _PreviewRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not preview_url_allowed(newurl):
            raise URLError("redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._in_p = False
        self.title_parts: list[str] = []
        self.p_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self._p_done = False

    def handle_starttag(self, tag, attrs):
        d = {str(k).lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (d.get("name") or d.get("property") or d.get("itemprop") or "").lower()
            content = d.get("content") or ""
            if name and content and name not in self.meta:
                self.meta[name] = content
        elif tag == "p" and not self._p_done:
            self._in_p = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "p" and self._in_p:
            self._in_p = False
            self._p_done = True

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        elif self._in_p and len("".join(self.p_parts)) < 400:
            self.p_parts.append(data)


def preview_url_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in ("localhost", "localhost.localdomain"):
        return False
    try:
        infos = socket.getaddrinfo(host, parsed.port or None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def _clean_text(value: str, limit: int) -> str:
    text = htmlmod.unescape(value or "")
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def parse_preview_html(raw: str, final_url: str) -> dict:
    parser = _MetaParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        pass
    meta = parser.meta
    title = meta.get("og:title") or meta.get("twitter:title") or "".join(parser.title_parts)
    desc = (
        meta.get("og:description")
        or meta.get("description")
        or meta.get("twitter:description")
        or " ".join(parser.p_parts)
    )
    image = meta.get("og:image") or meta.get("twitter:image") or ""
    if image:
        image = urljoin(final_url, image)
        if urlparse(image).scheme not in ("http", "https"):
            image = ""
    host = (urlparse(final_url).hostname or "").replace("www.", "")
    return {
        "ok": True,
        "url": final_url,
        "host": host,
        "title": _clean_text(title, 160),
        "description": _clean_text(desc, 320),
        "image": image,
    }


def fetch_preview(url: str) -> dict:
    now = time.time()
    cached = _PREVIEW_CACHE.get(url)
    if cached and now - cached[0] < PREVIEW_TTL:
        return cached[1]
    if len(url) > 2000 or not preview_url_allowed(url):
        payload = {"ok": False, "url": url, "host": "", "title": "", "description": "", "image": ""}
        return payload
    req = Request(
        url,
        headers={
            "User-Agent": "MarkdownViewer/1.0 (+local preview)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
        method="GET",
    )
    opener = build_opener(_PreviewRedirect)
    payload = {"ok": False, "url": url, "host": "", "title": "", "description": "", "image": ""}
    try:
        with opener.open(req, timeout=PREVIEW_TIMEOUT) as resp:
            final = resp.geturl() or url
            if not preview_url_allowed(final):
                return payload
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "xml" not in ctype and ctype:
                host = (urlparse(final).hostname or "").replace("www.", "")
                payload = {
                    "ok": True,
                    "url": final,
                    "host": host,
                    "title": host,
                    "description": "",
                    "image": "",
                }
            else:
                raw = resp.read(PREVIEW_MAX_BYTES + 1)
                if len(raw) > PREVIEW_MAX_BYTES:
                    raw = raw[:PREVIEW_MAX_BYTES]
                text = raw.decode("utf-8", errors="replace")
                payload = parse_preview_html(text, final)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        host = (urlparse(url).hostname or "").replace("www.", "")
        payload = {
            "ok": False,
            "url": url,
            "host": host,
            "title": host,
            "description": "Could not load a preview.",
            "image": "",
        }
    if len(_PREVIEW_CACHE) > 48:
        _PREVIEW_CACHE.clear()
    _PREVIEW_CACHE[url] = (now, payload)
    return payload


def is_safe(root: Path, rel: Path, skip: set[str] | None = None) -> bool:
    skip_dirs = skip if skip is not None else SKIP_DIRS
    try:
        resolved = (root / rel).resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    try:
        parts = resolved.relative_to(root.resolve()).parts
    except ValueError:
        return False
    return not any(part in skip_dirs for part in parts)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    file_cfg = _read_json(CONFIG_PATH)
    for key, value in file_cfg.items():
        if value is not None:
            cfg[key] = value
    local = _read_json(LOCAL_PATH)
    if isinstance(local.get("recent"), list):
        cfg["recent"] = local["recent"]
    if local.get("last"):
        cfg["last"] = local["last"]
    skip = cfg.get("skip_dirs") or sorted(SKIP_DIRS)
    cfg["skip_dirs"] = [str(x) for x in skip]
    return cfg


def save_local(cfg: dict) -> None:
    payload = {
        "recent": cfg.get("recent") or [],
        "last": cfg.get("last") or "",
    }
    tmp = LOCAL_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(LOCAL_PATH)


def expand_dir(raw: str) -> Path:
    return Path(raw or "~").expanduser().resolve()


def shortcut_items(cfg: dict) -> list[dict]:
    items = []
    seen: set[str] = set()
    for raw in cfg.get("shortcuts") or []:
        try:
            path = expand_dir(str(raw))
        except OSError:
            continue
        if not path.is_dir():
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        label = "Home" if path == Path.home() else (path.name or key)
        items.append({"name": label, "path": key})
    return items


def md_here(path: Path) -> int:
    n = 0
    try:
        for child in path.iterdir():
            if child.is_file() and child.suffix.lower() in MD_SUFFIXES:
                n += 1
    except OSError:
        return 0
    return n


def list_fs(path: Path, skip: set[str]) -> dict:
    dirs = []
    files = []
    try:
        children = list(path.iterdir())
    except OSError as err:
        raise OSError("cannot read folder: %s" % err) from err
    children.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
    for child in children[:400]:
        name = child.name
        if name.startswith(".") or name in skip:
            continue
        try:
            if child.is_dir():
                dirs.append({"name": name, "path": str(child.resolve()), "md": md_here(child)})
            elif child.is_file() and child.suffix.lower() in MD_SUFFIXES:
                files.append({"name": name})
        except OSError:
            continue
    parent = path.parent
    parent_s = str(parent) if parent != path else ""
    return {
        "path": str(path),
        "parent": parent_s,
        "dirs": dirs,
        "files": files,
        "md": md_here(path),
    }


class AppState:
    def __init__(self, cfg: dict, notes_dir: Path | None, title: str | None):
        self.lock = threading.Lock()
        self.cfg = cfg
        self.notes_dir = notes_dir
        self.title = title or (notes_dir.name if notes_dir else "Markdown")
        if notes_dir:
            self._remember(notes_dir)

    def skip(self) -> set[str]:
        return set(self.cfg.get("skip_dirs") or SKIP_DIRS)

    def _remember(self, path: Path) -> None:
        rec = {
            "name": path.name,
            "path": str(path),
            "md": len(list_notes(path, path.name, self.skip())),
        }
        recent = [r for r in (self.cfg.get("recent") or []) if r.get("path") != rec["path"]]
        recent.insert(0, rec)
        self.cfg["recent"] = recent[: int(self.cfg.get("recent_max") or 8)]
        self.cfg["last"] = rec["path"]
        try:
            save_local(self.cfg)
        except OSError:
            pass

    def open_folder(self, raw: str) -> dict:
        path = expand_dir(raw)
        if not path.is_dir():
            raise ValueError("not a folder")
        title = self.cfg.get("title") or path.name
        with self.lock:
            self.notes_dir = path
            self.title = title
            self._remember(path)
        notes = list_notes(path, title, self.skip())
        return {
            "ok": True,
            "path": str(path),
            "title": title,
            "defaultDoc": default_doc(notes),
            "md": len(notes),
        }

    def public_state(self) -> dict:
        with self.lock:
            opened = str(self.notes_dir) if self.notes_dir else ""
            title = self.title
            cfg = dict(self.cfg)
        return {
            "version": VERSION,
            "open": bool(opened),
            "path": opened,
            "title": title,
            "start_dir": cfg.get("start_dir") or "~",
            "last": cfg.get("last") or opened,
            "gutter": cfg.get("gutter") or "1.75rem",
            "recent": cfg.get("recent") or [],
            "shortcuts": shortcut_items(cfg),
        }


def make_handler(app_dir: Path, state: AppState):
    api_get = {"/api/notes", "/api/preview", "/api/fs", "/api/state"}
    api_all = api_get | {"/api/open"}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            with state.lock:
                root = state.notes_dir
            super().__init__(*args, directory=str(root or app_dir), **kwargs)

        def _local(self) -> bool:
            host = self.client_address[0]
            return host in ("127.0.0.1", "::1")

        def _send_json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def end_headers(self) -> None:
            path = urlparse(self.path).path
            ext = Path(unquote(path)).suffix.lower()
            if ext in NO_CACHE_EXT or path in APP_PATHS or path in api_all:
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
            if bare in ("/viewer.html", "/viewer.css", "/viewer.js", "/splash.js"):
                return str(app_dir / bare.lstrip("/"))
            return super().translate_path(path)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                self._send_json(state.public_state())
                return
            if parsed.path == "/api/fs":
                if not self._local():
                    self._send_json({"error": "folder browser is localhost only"}, 403)
                    return
                raw = (parse_qs(parsed.query).get("path") or [""])[0]
                try:
                    path = expand_dir(raw or state.cfg.get("start_dir") or "~")
                    if not path.is_dir():
                        self._send_json({"error": "not a folder"}, 400)
                        return
                    self._send_json(list_fs(path, state.skip()))
                except OSError as err:
                    self._send_json({"error": str(err)}, 400)
                return
            if parsed.path == "/api/notes":
                with state.lock:
                    notes_dir = state.notes_dir
                    title = state.title
                if notes_dir is None:
                    self._send_json({"error": "no folder open", "notes": []}, 409)
                    return
                notes = list_notes(notes_dir, title, state.skip())
                self._send_json(
                    {
                        "title": title,
                        "defaultDoc": default_doc(notes),
                        "notes": notes,
                        "path": str(notes_dir),
                    }
                )
                return
            if parsed.path == "/api/preview":
                qs = parse_qs(parsed.query)
                url = (qs.get("url") or [""])[0]
                self._send_json(fetch_preview(url))
                return

            rel = Path(unquote(parsed.path.lstrip("/")))
            if parsed.path not in APP_PATHS and parsed.path not in ("",):
                with state.lock:
                    notes_dir = state.notes_dir
                if notes_dir is None or not is_safe(notes_dir, rel, state.skip()):
                    self.send_error(404, "Not found")
                    return
            super().do_GET()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/open":
                self.send_error(404, "Not found")
                return
            if not self._local():
                self._send_json({"error": "opening a folder is localhost only"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            if length < 0 or length > 8000:
                self._send_json({"error": "bad request"}, 400)
                return
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                self._send_json({"error": "invalid json"}, 400)
                return
            path = (body.get("path") if isinstance(body, dict) else "") or ""
            try:
                self._send_json(state.open_folder(str(path)))
            except (OSError, ValueError) as err:
                self._send_json({"error": str(err)}, 400)

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("%s — %s\n" % (self.address_string(), fmt % args))

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve a folder of markdown files as a local webpage."
    )
    parser.add_argument(
        "--version",
        action="version",
        version="markdown-viewer %s" % VERSION,
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=None,
        help="Optional folder to open (otherwise pick one on the splash page)",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--title",
        default=None,
        help="Name in the header (default: folder name)",
    )
    args = parser.parse_args()

    cfg = load_config()
    if args.host:
        cfg["host"] = args.host
    if args.port is not None:
        cfg["port"] = args.port
    if args.title:
        cfg["title"] = args.title

    notes_dir = None
    if args.root:
        notes_dir = Path(args.root).expanduser().resolve()
        if not notes_dir.is_dir():
            print("not a folder: %s" % notes_dir, file=sys.stderr)
            return 2
    elif cfg.get("last"):
        try:
            last = expand_dir(str(cfg.get("last")))
        except OSError:
            last = None
        if last is not None and last.is_dir():
            notes_dir = last

    title = cfg.get("title")
    state = AppState(cfg, notes_dir, title)
    host = str(cfg.get("host") or "127.0.0.1")
    port = int(cfg.get("port") or 8765)
    handler = make_handler(APP_DIR, state)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = "http://%s:%s" % (host, port)
    print("Markdown viewer %s" % VERSION, flush=True)
    print("  config  %s" % CONFIG_PATH, flush=True)
    if notes_dir:
        print("  folder  %s" % notes_dir, flush=True)
    else:
        print("  pick a folder at %s" % url, flush=True)
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
