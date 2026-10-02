#!/usr/bin/env python3
"""Local markdown viewer.

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python serve.py
    .venv/bin/python serve.py /path/to/notes

YAKE (in requirements.txt) ranks multi-word keyphrases. Without it the
server still runs and falls back to phrase counts. HTML/JS have no build step.

Open http://127.0.0.1:8765 and pick a folder on the splash page.
Host/port/start directory live in config.json next to this script.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmlmod
import ipaddress
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

try:
    import yake as yake_lib
except ImportError:
    yake_lib = None

# Single source of truth for:
#   python3 serve.py --version
#   startup log
#   GET /api/state → version  (splash header + reader rail; never hard-code in HTML/JS)
#
# Bump here, then move Unreleased in RELEASE_NOTES.md and tag vX.Y.Z.
# Current: 0.2.0 — desktop apps, companion Ask, YAKE keywords, folder memory.
VERSION = "0.2.0"

def bundled_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Markdown Viewer"
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "Markdown Viewer"
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "markdown-viewer"
    path.mkdir(parents=True, exist_ok=True)
    return path


APP_DIR = bundled_dir()
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
CONFIG_PATH = user_data_dir() / "config.json" if getattr(sys, "frozen", False) else APP_DIR / "config.json"
LOCAL_PATH = (
    Path(os.environ["MDVIEW_LOCAL"]).expanduser()
    if os.environ.get("MDVIEW_LOCAL")
    else user_data_dir() / "config.local.json"
)
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8765,
    "title": None,
    "start_dir": "~",
    "recent_max": 8,
    "gutter": "1.75rem",
    "shortcuts": ["~", "~/Documents", "~/Desktop", "~/Downloads"],
    "skip_dirs": sorted(SKIP_DIRS),
    "recent": [],
    "last": "",
    "ai": {"default_provider": "", "providers": {}},
}
PORTABLE_KEYS = (
    "host",
    "port",
    "title",
    "start_dir",
    "recent_max",
    "gutter",
    "shortcuts",
    "skip_dirs",
)
AI_KEY_MASK = ".........."
AI_DIR = APP_DIR / "ai"
PROVIDERS_PATH = AI_DIR / "providers.json"
PROMPTS_DIR = AI_DIR / "prompts"
NOTE_MAX_CHARS = 200000
AI_TIMEOUT = 120
DEFAULT_PROMPT_SYSTEM = (
    "You read and edit markdown notes. Return markdown only. "
    "Do not wrap the whole answer in a single fence."
)
MEMORY_NAME = "_memory.json"
MEMORY_VERSION = 1
MEMORY_WALK_MAX = 12
CHAT_DIR = "_chats"
CHAT_HISTORY_MAX = 24
CHAT_SYSTEM = (
    "You are chatting about the open markdown note. Return markdown only. "
    "Do not wrap the whole answer in a single fence. "
    "When you mention another note, use a relative markdown link. "
    "You may include markdown images for files that already exist "
    "(relative paths or https URLs). Do not invent binary image files. "
    "Later turns do not repeat the full note unless the file changes."
)
DOC_KEYWORD_MAX = 20
FOLDER_KEYWORD_MAX = 30
RELATED_MAX = 5
HEADING_WEIGHT = 3
KEYWORD_MIN_COUNT = 3
KEYWORD_MIN_WORDS = 2
YAKE_NGRAM = 3
YAKE_TOP = 50
STOPWORDS_PATH = AI_DIR / "stopwords.txt"
TOKEN_RE = re.compile(r"[a-z][a-z0-9\-']{0,40}", re.I)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
IMG_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
INLINE_CODE_RE = re.compile(r"`[^`]+`")
URL_RE = re.compile(r"https?://\S+", re.I)
_STOPWORDS: set[str] | None = None
BUILTIN_STOPWORDS = {
    "a", "about", "after", "all", "also", "an", "and", "any", "are", "as", "at",
    "be", "because", "been", "before", "being", "between", "both", "but", "by",
    "can", "could", "did", "do", "does", "doing", "down", "during", "each",
    "for", "from", "had", "has", "have", "having", "he", "her", "here", "him",
    "his", "how", "i", "if", "in", "into", "is", "it", "its", "just", "me",
    "more", "most", "my", "no", "not", "now", "of", "on", "once", "only", "or",
    "other", "our", "out", "over", "same", "she", "should", "so", "some", "such",
    "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "those", "through", "to", "too", "under", "until", "up", "very",
    "was", "we", "were", "what", "when", "where", "which", "while", "who", "why",
    "will", "with", "would", "you", "your", "http", "https", "www", "com",
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
            if any(is_system_name(part) or part in skip_dirs for part in rel.parts):
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
    sources = [APP_DIR / "config.json"]
    if CONFIG_PATH.resolve() != sources[0].resolve():
        sources.append(CONFIG_PATH)
    for path in sources:
        for key, value in _read_json(path).items():
            if value is not None and key != "ai":
                cfg[key] = value
    local = _read_json(LOCAL_PATH)
    if isinstance(local.get("recent"), list):
        cfg["recent"] = local["recent"]
    if local.get("last"):
        cfg["last"] = local["last"]
    skip = cfg.get("skip_dirs") or sorted(SKIP_DIRS)
    cfg["skip_dirs"] = [str(x) for x in skip]
    cfg["ai"] = normalize_ai(local.get("ai") if isinstance(local.get("ai"), dict) else {})
    return cfg


def save_local(cfg: dict) -> None:
    payload = {
        "recent": cfg.get("recent") or [],
        "last": cfg.get("last") or "",
        "ai": normalize_ai(cfg.get("ai") if isinstance(cfg.get("ai"), dict) else {}),
    }
    _write_json(LOCAL_PATH, payload)


def save_portable(cfg: dict) -> None:
    payload = {}
    for key in PORTABLE_KEYS:
        if key in cfg:
            payload[key] = cfg[key]
    _write_json(CONFIG_PATH, payload)


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def normalize_base_url(raw: str) -> str:
    url = (raw or "").strip()
    if url.endswith("/"):
        url = url[:-1]
    lower = url.lower()
    for suffix in ("/chat/completions", "/completions", "/models"):
        if lower.endswith(suffix):
            url = url[: -len(suffix)]
            if url.endswith("/"):
                url = url[:-1]
            break
    return url


def is_mask_key(value: str) -> bool:
    s = (value or "").strip()
    return s in ("", AI_KEY_MASK, "***", "********")


def provider_id(raw: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (raw or "").strip().lower())
    text = text.strip("-_") or "custom"
    return text[:40]


def normalize_provider(pid: str, raw: dict, previous: dict | None = None) -> dict:
    prev = previous or {}
    incoming = raw.get("api_key") if isinstance(raw, dict) else ""
    key = prev.get("api_key") or ""
    if isinstance(incoming, str) and not is_mask_key(incoming):
        key = incoming.strip()
    models = raw.get("models") if isinstance(raw, dict) else None
    if isinstance(models, str):
        models = [m.strip() for m in models.replace(",", "\n").splitlines() if m.strip()]
    elif isinstance(models, list):
        models = [str(m).strip() for m in models if str(m).strip()]
    else:
        models = list(prev.get("models") or [])
    label = (raw.get("label") if isinstance(raw, dict) else "") or prev.get("label") or pid
    base = normalize_base_url(
        str((raw.get("base_url") if isinstance(raw, dict) else "") or prev.get("base_url") or "")
    )
    service = (raw.get("service") if isinstance(raw, dict) else "") or prev.get("service") or pid
    return {
        "id": pid,
        "label": str(label).strip() or pid,
        "base_url": base,
        "api_key": key,
        "models": models,
        "service": str(service).strip() or pid,
    }


def normalize_ai(raw: dict) -> dict:
    providers_in = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    providers = {}
    for key, value in providers_in.items():
        pid = provider_id(str(key))
        if not isinstance(value, dict):
            continue
        providers[pid] = normalize_provider(pid, value, None)
    default = provider_id(str(raw.get("default_provider") or ""))
    if default not in providers:
        default = next(iter(providers), "")
    return {"default_provider": default, "providers": providers}


def redact_provider(p: dict) -> dict:
    key = p.get("api_key") or ""
    return {
        "id": p.get("id") or "",
        "label": p.get("label") or "",
        "base_url": p.get("base_url") or "",
        "models": list(p.get("models") or []),
        "service": p.get("service") or "",
        "api_key_set": bool(key),
        "api_key_length": len(key),
        "api_key": AI_KEY_MASK if key else "",
    }


def load_provider_catalog() -> list[dict]:
    try:
        data = json.loads(PROVIDERS_PATH.read_text(encoding="utf-8")) if PROVIDERS_PATH.is_file() else []
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    rows = []
    for raw in data:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        models = raw.get("models") or []
        if isinstance(models, str):
            models = [m.strip() for m in models.replace(",", "\n").splitlines() if m.strip()]
        rows.append(
            {
                "id": str(raw["id"]),
                "label": str(raw.get("label") or raw["id"]),
                "suggested_id": str(raw.get("suggested_id") or raw["id"]),
                "base_url": str(raw.get("base_url") or ""),
                "models": [str(m) for m in models if str(m).strip()],
                "needs_key": bool(raw.get("needs_key", True)),
                "hint": str(raw.get("hint") or ""),
            }
        )
    return rows


def load_prompts() -> list[dict]:
    items = []
    if not PROMPTS_DIR.is_dir():
        return items
    for path in sorted(PROMPTS_DIR.glob("*.json")):
        raw = _read_json(path)
        if not raw:
            continue
        pid = str(raw.get("id") or path.stem).strip()
        if not pid:
            continue
        items.append(
            {
                "id": pid,
                "label": str(raw.get("label") or pid),
                "description": str(raw.get("description") or ""),
                "system": str(raw.get("system") or DEFAULT_PROMPT_SYSTEM),
                "user": str(raw.get("user") or "{{note}}"),
                "hidden": bool(raw.get("hidden")),
            }
        )
    return items


def public_prompts() -> list[dict]:
    return [
        {
            "id": p["id"],
            "label": p["label"],
            "description": p["description"],
            "requires_prompt": "{{prompt}}" in (p.get("user") or ""),
        }
        for p in load_prompts()
        if not p.get("hidden")
    ]


def prompt_by_id(pid: str) -> dict | None:
    want = (pid or "").strip()
    for row in load_prompts():
        if row["id"] == want:
            return row
    return None


def render_prompt(template: str, note: str, extra: str, keywords: str = "") -> str:
    text = template.replace("{{note}}", note or "")
    text = text.replace("{{keywords}}", keywords or "")
    if "{{prompt}}" in text:
        text = text.replace("{{prompt}}", extra or "")
    elif extra:
        text = extra + "\n\n" + text
    return text.strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_stopwords() -> set[str]:
    global _STOPWORDS
    if _STOPWORDS is not None:
        return _STOPWORDS
    words = set(BUILTIN_STOPWORDS)
    try:
        if STOPWORDS_PATH.is_file():
            for line in STOPWORDS_PATH.read_text(encoding="utf-8").splitlines():
                token = line.strip().lower()
                if token and not token.startswith("#"):
                    words.add(token)
    except OSError:
        pass
    _STOPWORDS = words
    return words


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def empty_memory() -> dict:
    return {"version": MEMORY_VERSION, "updated": "", "docs": {}, "topics": {}, "keywords": []}


def read_memory_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def memory_pointer_target(data: dict) -> str:
    raw = data.get("ref") or data.get("fk") or ""
    return str(raw).strip() if isinstance(raw, str) else ""


def is_memory_pointer(data: dict | None) -> bool:
    return bool(data) and bool(memory_pointer_target(data or {}))


def _normalize_memory(data: dict) -> dict:
    docs = data.get("docs")
    data["docs"] = docs if isinstance(docs, dict) else {}
    topics = data.get("topics")
    data["topics"] = topics if isinstance(topics, dict) else {}
    keys = data.get("keywords")
    data["keywords"] = keys if isinstance(keys, list) else []
    data["version"] = MEMORY_VERSION
    return data


def _stop_memory_walk(parent: Path, home: Path) -> bool:
    if parent == parent.parent:
        return True
    if parent == home:
        return True
    posix = parent.as_posix()
    return posix in ("/", "/tmp", "/var", "/private", "/Users", "/home")


def follow_memory_ref(from_dir: Path, data: dict, seen: set[str]) -> Path | None:
    ref = memory_pointer_target(data)
    if not ref:
        return None
    target = (from_dir / ref).resolve()
    if target.is_file():
        mem_dir = target.parent
        mem_file = target
    elif target.is_dir():
        mem_dir = target
        mem_file = target / MEMORY_NAME
    else:
        return None
    key = str(mem_file)
    if key in seen:
        return None
    if not mem_file.is_file():
        return None
    seen.add(key)
    nested = read_memory_json(mem_file)
    if is_memory_pointer(nested):
        return follow_memory_ref(mem_dir, nested or {}, seen)
    return mem_dir


def resolve_memory_dir(notes_dir: Path) -> Path:
    here = notes_dir.resolve()
    local = here / MEMORY_NAME
    seen: set[str] = set()
    if local.is_file():
        data = read_memory_json(local)
        if is_memory_pointer(data):
            followed = follow_memory_ref(here, data or {}, seen)
            if followed is not None:
                return followed
        return here
    home = Path.home().resolve()
    cur = here
    for _ in range(MEMORY_WALK_MAX):
        parent = cur.parent
        if _stop_memory_walk(parent, home):
            break
        candidate = parent / MEMORY_NAME
        if candidate.is_file():
            data = read_memory_json(candidate)
            if is_memory_pointer(data):
                followed = follow_memory_ref(parent, data or {}, seen)
                if followed is not None:
                    return followed
            else:
                return parent
        cur = parent
    return here


def memory_path(notes_dir: Path) -> Path:
    return resolve_memory_dir(notes_dir) / MEMORY_NAME


def memory_prefix(notes_dir: Path, mem_dir: Path) -> str:
    try:
        rel = notes_dir.resolve().relative_to(mem_dir.resolve())
    except ValueError:
        return ""
    posix = rel.as_posix()
    return "" if posix == "." else posix


def to_memory_key(prefix: str, rel: str) -> str:
    rel_posix = Path(rel or "").as_posix().lstrip("/")
    if not prefix:
        return rel_posix
    if not rel_posix:
        return prefix
    return prefix + "/" + rel_posix


def from_memory_key(prefix: str, key: str) -> str | None:
    path = Path(key or "").as_posix().lstrip("/")
    if not prefix:
        return path
    if path.startswith(prefix + "/"):
        return path[len(prefix) + 1 :]
    return None


def expose_paths(values: list, prefix: str) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        local = from_memory_key(prefix, str(raw or ""))
        if local:
            out.append(local)
    return out


def write_memory_pointer(notes_dir: Path, mem_dir: Path) -> None:
    notes = notes_dir.resolve()
    dest = mem_dir.resolve()
    if notes == dest:
        return
    local = notes / MEMORY_NAME
    if local.is_file():
        data = read_memory_json(local)
        if data and not is_memory_pointer(data):
            return
        if is_memory_pointer(data):
            return
    try:
        rel = Path(os.path.relpath(str(dest), str(notes))).as_posix()
        payload = {"version": MEMORY_VERSION, "ref": rel}
        local.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def load_memory(notes_dir: Path) -> dict:
    path = memory_path(notes_dir)
    if not path.is_file():
        return empty_memory()
    data = read_memory_json(path)
    if not data or is_memory_pointer(data):
        return empty_memory()
    return _normalize_memory(data)


def save_memory(notes_dir: Path, data: dict) -> bool:
    mem_dir = resolve_memory_dir(notes_dir)
    path = mem_dir / MEMORY_NAME
    payload = dict(data)
    payload.pop("ref", None)
    payload.pop("fk", None)
    payload["version"] = MEMORY_VERSION
    payload["updated"] = utc_now()
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        write_memory_pointer(notes_dir, mem_dir)
        return True
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def is_system_name(name: str) -> bool:
    return name.startswith(".") or name.startswith("_")


def new_chat_id() -> str:
    return uuid.uuid4().hex[:12]


def chat_path(notes_dir: Path, rel: str) -> Path:
    rel_path = Path((rel or "").replace("\\", "/"))
    if rel_path.is_absolute() or ".." in rel_path.parts or not rel_path.parts:
        raise ValueError("bad chat path")
    if is_system_name(rel_path.name):
        raise ValueError("not a note")
    dest = (notes_dir / CHAT_DIR / rel_path).with_name(rel_path.name + ".jsonl")
    root = (notes_dir / CHAT_DIR).resolve()
    try:
        dest.resolve().relative_to(root)
    except ValueError as err:
        raise ValueError("chat path escape") from err
    return dest


def load_chat(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("id"):
            rows.append(row)
    return rows


def write_chat(path: Path, rows: list[dict]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        blob = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        tmp.write_text(blob, encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def append_chat(path: Path, row: dict) -> bool:
    rows = load_chat(path)
    rows.append(row)
    return write_chat(path, rows)


def public_chat_message(row: dict) -> dict:
    return {
        "id": str(row.get("id") or ""),
        "ts": str(row.get("ts") or ""),
        "role": str(row.get("role") or ""),
        "kind": str(row.get("kind") or "chat"),
        "text": str(row.get("text") or ""),
        "preset": str(row.get("preset") or ""),
        "model": str(row.get("model") or ""),
        "note_sha": str(row.get("note_sha") or ""),
        "ok": row.get("ok", True) is not False,
        "error": str(row.get("error") or ""),
    }


def last_snapshot_sha(rows: list[dict]) -> str:
    sha = ""
    for row in rows:
        if row.get("kind") in ("note_snapshot", "note_changed") and row.get("note_sha"):
            sha = str(row.get("note_sha") or "")
    return sha


def chat_user_text(spec: dict, extra: str) -> str:
    extra = (extra or "").strip()
    template = spec.get("user") or "{{prompt}}"
    stripped = template.replace("{{note}}", "").replace("{{keywords}}", "")
    stripped = re.sub(r"(?:\n---\s*)+$", "", stripped).strip()
    if "{{prompt}}" in stripped:
        return render_prompt(stripped, "", extra)
    if extra and stripped:
        return extra + "\n\n" + stripped
    return extra or stripped


def compact_briefing(rel: str, sha: str, text: str, doc: dict | None) -> str:
    doc = doc if isinstance(doc, dict) else {}
    title = doc.get("title") or extract_title(text, Path(rel).stem.replace("-", " "))
    headings = list(doc.get("headings") or extract_headings(text))
    keywords = format_keywords_for_prompt(doc.get("keywords") or [])
    tldr = [str(x) for x in (doc.get("tldr") or []) if str(x).strip()]
    lines = [
        "Open note: %s" % rel,
        "Title: %s" % title,
        "SHA: %s" % sha,
    ]
    if headings:
        lines.append("Headings: " + " | ".join(str(h) for h in headings[:12]))
    if keywords and keywords != "(none)":
        lines.append("Keywords: " + keywords)
    if tldr:
        lines.append("TL;DR: " + " ".join(tldr[:3]))
    return "\n".join(lines)


def history_for_model(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        role = row.get("role")
        kind = row.get("kind") or "chat"
        if role not in ("user", "assistant"):
            continue
        if kind not in ("chat", "preset"):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        if row.get("ok") is False:
            continue
        out.append({"role": role, "content": text})
    return out[-CHAT_HISTORY_MAX:]


def build_chat_messages(
    spec: dict,
    briefing: str,
    body: str,
    history: list[dict],
    user_text: str,
    attach_note: bool,
) -> list[dict]:
    system = (spec.get("system") or CHAT_SYSTEM).strip()
    system = system + "\n\n" + briefing
    messages = [{"role": "system", "content": system}]
    if attach_note:
        messages.append(
            {
                "role": "user",
                "content": (
                    "Full markdown for this note. Later turns will not repeat it "
                    "unless the file hash changes.\n\n" + (body or "")
                ),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": "I have the note. Ask away.",
            }
        )
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    return messages


def raw_tokens(text: str) -> list[str]:
    out = []
    for match in TOKEN_RE.finditer(text or ""):
        tok = match.group(0).lower().strip("-'")
        if len(tok) < 2 or tok.isdigit():
            continue
        out.append(tok)
    return out


def clean_line(text: str) -> str:
    text = IMG_RE.sub(r" \1 ", text or "")
    text = MD_LINK_RE.sub(r" \1 ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = URL_RE.sub(" ", text)
    return text


def iter_weighted_lines(text: str):
    in_fence = False
    fence_mark = ""
    for line in (text or "").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            mark = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_mark = mark
            elif stripped.startswith(fence_mark):
                in_fence = False
                fence_mark = ""
            continue
        if in_fence:
            continue
        heading = HEADING_RE.match(line)
        if heading:
            title = clean_line(heading.group(2)).strip()
            if title:
                yield title, HEADING_WEIGHT
            continue
        cleaned = clean_line(line)
        if cleaned.strip():
            yield cleaned, 1


def extract_headings(text: str) -> list[str]:
    found = []
    in_fence = False
    fence_mark = ""
    for line in (text or "").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            mark = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_mark = mark
            elif stripped.startswith(fence_mark):
                in_fence = False
                fence_mark = ""
            continue
        if in_fence:
            continue
        heading = HEADING_RE.match(line)
        if heading:
            title = clean_line(heading.group(2)).strip()
            if title:
                found.append(title)
            if len(found) >= 40:
                break
    return found


def extract_title(text: str, fallback: str) -> str:
    for line in (text or "").splitlines()[:40]:
        if line.startswith("# "):
            title = clean_line(line[2:]).strip()
            if title:
                return title
    return fallback


def resolve_local_note(href: str, from_rel: str, known: set[str]) -> str:
    raw = unquote((href or "").split("#")[0].split("?")[0].strip())
    if not raw or raw.startswith(("http://", "https://", "mailto:", "tel:", "data:")):
        return ""
    if raw.startswith("/"):
        cand = raw.lstrip("/")
    else:
        base = Path(from_rel).parent
        cand = (base / raw).as_posix() if str(base) != "." else raw
    parts: list[str] = []
    for part in cand.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    posix = "/".join(parts)
    if posix in known:
        return posix
    for suffix in MD_SUFFIXES:
        if posix + suffix in known:
            return posix + suffix
    return ""


def extract_local_links(text: str, from_rel: str, known: set[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    in_fence = False
    fence_mark = ""
    for line in (text or "").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            mark = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_mark = mark
            elif stripped.startswith(fence_mark):
                in_fence = False
                fence_mark = ""
            continue
        if in_fence:
            continue
        for match in MD_LINK_RE.finditer(line):
            dest = resolve_local_note(match.group(2), from_rel, known)
            if dest and dest != from_rel and dest not in seen:
                seen.add(dest)
                found.append(dest)
    return found


def _is_subphrase(inner: str, outer: str) -> bool:
    a = inner.split()
    b = outer.split()
    if not a or len(a) >= len(b):
        return False
    span = len(a)
    for i in range(len(b) - span + 1):
        if b[i : i + span] == a:
            return True
    return False


def phrase_tf(text: str) -> Counter:
    """Count 2–3 word phrases. Stopwords break a phrase; repeated same-token skipped."""
    stops = load_stopwords()
    phrases: Counter = Counter()
    for line, weight in iter_weighted_lines(text):
        tokens = raw_tokens(line)
        for n in (2, 3):
            for i in range(len(tokens) - n + 1):
                window = tokens[i : i + n]
                if any(t in stops for t in window):
                    continue
                if len(set(window)) < 2:
                    continue
                phrases[" ".join(window)] += weight
    return phrases


def plain_for_yake(text: str) -> str:
    lines: list[str] = []
    for line, weight in iter_weighted_lines(text):
        lines.extend([line] * max(1, int(weight)))
    return "\n".join(lines)


def yake_rank(text: str) -> list[str]:
    if yake_lib is None:
        return []
    blob = plain_for_yake(text)
    if not blob.strip():
        return []
    stops = load_stopwords()
    try:
        extractor = yake_lib.KeywordExtractor(
            lan="en",
            n=YAKE_NGRAM,
            top=YAKE_TOP,
            dedup_lim=0.8,
            window_size=1,
            stopwords=set(stops),
        )
        rows = extractor.extract_keywords(blob)
    except Exception:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw, _score in rows or []:
        parts = raw_tokens(str(raw or ""))
        if len(parts) < KEYWORD_MIN_WORDS:
            continue
        if parts[0] in stops or parts[-1] in stops:
            continue
        if len(set(parts)) < 2:
            continue
        key = " ".join(parts)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _eligible_phrases(phrases: Counter) -> dict[str, int]:
    out: dict[str, int] = {}
    for term, n in phrases.items():
        n = int(n)
        if n < KEYWORD_MIN_COUNT:
            continue
        parts = term.split()
        if len(parts) < KEYWORD_MIN_WORDS or len(set(parts)) < 2:
            continue
        out[term] = n
    return out


def pick_keywords(
    phrases: Counter,
    limit: int = DOC_KEYWORD_MAX,
    ranked: list[str] | None = None,
) -> list[list]:
    """Multi-word only, count >= 3. Two-word phrases first; YAKE breaks ties."""
    eligible = _eligible_phrases(phrases)
    by_len: dict[int, list[str]] = {2: [], 3: []}
    seen: set[str] = set()
    for term in ranked or []:
        if term in seen or term not in eligible:
            continue
        seen.add(term)
        by_len.setdefault(len(term.split()), []).append(term)
    for term, n in sorted(eligible.items(), key=lambda kv: (-kv[1], kv[0])):
        if term in seen:
            continue
        seen.add(term)
        by_len.setdefault(len(term.split()), []).append(term)
    have: list[str] = []
    covered: set[str] = set()
    picked: list[tuple[int, str]] = []
    for length in (2, 3):
        for term in by_len.get(length) or []:
            if len(picked) >= limit:
                break
            parts = term.split()
            if any(_is_subphrase(term, prev) or _is_subphrase(prev, term) for prev in have):
                continue
            if length > 2 and all(tok in covered for tok in parts):
                continue
            picked.append((eligible[term], term))
            have.append(term)
            covered.update(parts)
    picked.sort(key=lambda row: (-row[0], row[1]))
    return [[term, n] for n, term in picked[:limit]]


def keyword_counts(text: str, limit: int = DOC_KEYWORD_MAX) -> list[list]:
    return pick_keywords(phrase_tf(text), limit, yake_rank(text))


def rebuild_folder_index(mem: dict) -> None:
    df: Counter = Counter()
    tf: Counter = Counter()
    term_docs: dict[str, list[str]] = {}
    docs = mem.get("docs") if isinstance(mem.get("docs"), dict) else {}
    for path, doc in docs.items():
        if not isinstance(doc, dict):
            continue
        seen = set()
        for pair in doc.get("keywords") or []:
            if not (isinstance(pair, (list, tuple)) and len(pair) >= 2):
                continue
            term = str(pair[0]).strip()
            try:
                n = int(pair[1])
            except (TypeError, ValueError):
                continue
            if not term:
                continue
            tf[term] += n
            seen.add(term)
        for term in seen:
            df[term] += 1
            term_docs.setdefault(term, []).append(path)
    ranked = sorted(df.keys(), key=lambda t: (-df[t], -tf[t], t))[:FOLDER_KEYWORD_MAX]
    mem["keywords"] = [[term, int(df[term])] for term in ranked]
    mem["topics"] = {term: term_docs[term] for term in ranked}


def related_for(path: str, doc: dict, mem: dict, known: set[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for href in doc.get("links") or []:
        if href and href != path and href in known and href not in seen:
            seen.add(href)
            out.append(href)
    my_terms = {str(pair[0]) for pair in (doc.get("keywords") or [])[:10] if isinstance(pair, (list, tuple)) and pair}
    scored: list[tuple[int, str]] = []
    docs = mem.get("docs") if isinstance(mem.get("docs"), dict) else {}
    for other, odoc in docs.items():
        if other == path or not isinstance(odoc, dict):
            continue
        other_terms = {
            str(pair[0])
            for pair in (odoc.get("keywords") or [])[:10]
            if isinstance(pair, (list, tuple)) and pair
        }
        overlap = len(my_terms & other_terms)
        if overlap >= 2:
            scored.append((overlap, other))
    scored.sort(key=lambda row: (-row[0], row[1]))
    for _, other in scored:
        if other in seen or other not in known:
            continue
        seen.add(other)
        out.append(other)
        if len(out) >= RELATED_MAX:
            break
    return out[:RELATED_MAX]


def cheap_doc(text: str, rel: str, known: set[str], sha: str, nbytes: int, prev: dict | None = None) -> dict:
    headings = extract_headings(text)
    title = extract_title(text, Path(rel).stem.replace("-", " "))
    keywords = keyword_counts(text)
    links = extract_local_links(text, rel, known)
    prev = prev if isinstance(prev, dict) else {}
    return {
        "sha256": sha,
        "bytes": nbytes,
        "title": title,
        "headings": headings,
        "links": links,
        "keywords": keywords,
        "related": [],
        "topics": [row[0] for row in keywords[:8]],
        "tldr": list(prev.get("tldr") or []) if prev.get("sha256") == sha else [],
        "next_action": (prev.get("next_action") or "") if prev.get("sha256") == sha else "",
        "important": (prev.get("important") or "") if prev.get("sha256") == sha else "",
        "rich": bool(prev.get("rich")) if prev.get("sha256") == sha else False,
        "seen_at": utc_now(),
        "visits": int(prev.get("visits") or 0) + 1,
    }


def prune_memory(mem: dict, known: set[str], scope: str = "") -> None:
    docs = mem.get("docs") if isinstance(mem.get("docs"), dict) else {}
    kept: dict = {}
    for path, doc in docs.items():
        if scope and path != scope and not path.startswith(scope + "/"):
            kept[path] = doc
            continue
        if path in known:
            kept[path] = doc
    mem["docs"] = kept


def apply_visit(
    mem: dict,
    rel: str,
    text: str,
    sha: str,
    nbytes: int,
    known: set[str],
    scope: str = "",
) -> tuple[dict, bool]:
    docs = mem.setdefault("docs", {})
    prev = docs.get(rel) if isinstance(docs.get(rel), dict) else {}
    doc = cheap_doc(text, rel, known, sha, nbytes, prev)
    fresh = prev.get("sha256") != sha or not prev.get("keywords")
    prune_memory(mem, known, scope)
    docs = mem.setdefault("docs", {})
    docs[rel] = doc
    doc["related"] = related_for(rel, doc, mem, known)
    docs[rel] = doc
    rebuild_folder_index(mem)
    return doc, fresh


def parse_json_object(text: str) -> dict | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def apply_pack(doc: dict, pack: dict) -> dict:
    out = dict(doc)
    tldr = pack.get("tldr")
    bullets = []
    if isinstance(tldr, list):
        bullets = [str(x).strip() for x in tldr if str(x).strip()][:3]
    elif isinstance(tldr, str) and tldr.strip():
        bullets = [tldr.strip()]
    out["tldr"] = bullets
    out["next_action"] = str(pack.get("next_action") or "").strip()
    out["important"] = str(pack.get("important") or "").strip()
    topics = pack.get("topics")
    if isinstance(topics, list):
        tags = [str(x).strip() for x in topics if str(x).strip()][:8]
        if tags:
            out["topics"] = tags
    out["rich"] = True
    out["seen_at"] = utc_now()
    return out


def format_keywords_for_prompt(keywords: list) -> str:
    rows = []
    for pair in keywords or []:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            rows.append("%s (%s)" % (pair[0], pair[1]))
    return ", ".join(rows) if rows else "(none)"


def public_doc(doc: dict, prefix: str = "") -> dict:
    return {
        "sha256": doc.get("sha256") or "",
        "bytes": int(doc.get("bytes") or 0),
        "title": doc.get("title") or "",
        "headings": list(doc.get("headings") or []),
        "links": expose_paths(list(doc.get("links") or []), prefix),
        "keywords": list(doc.get("keywords") or []),
        "related": expose_paths(list(doc.get("related") or []), prefix),
        "topics": list(doc.get("topics") or []),
        "tldr": list(doc.get("tldr") or []),
        "next_action": doc.get("next_action") or "",
        "important": doc.get("important") or "",
        "rich": bool(doc.get("rich")),
        "seen_at": doc.get("seen_at") or "",
        "visits": int(doc.get("visits") or 0),
    }


def redact_ai(ai: dict) -> dict:
    providers = {}
    for pid, p in (ai.get("providers") or {}).items():
        providers[pid] = redact_provider(p)
    return {
        "default_provider": ai.get("default_provider") or "",
        "providers": providers,
        "catalog": load_provider_catalog(),
        "prompts": public_prompts(),
    }


def portable_public(cfg: dict) -> dict:
    return {
        "host": cfg.get("host") or "127.0.0.1",
        "port": int(cfg.get("port") or 8765),
        "title": cfg.get("title"),
        "start_dir": cfg.get("start_dir") or "~",
        "recent_max": int(cfg.get("recent_max") or 8),
        "gutter": cfg.get("gutter") or "1.75rem",
        "shortcuts": list(cfg.get("shortcuts") or []),
        "skip_dirs": list(cfg.get("skip_dirs") or []),
        "restart": "host and port apply after you restart serve.py",
    }


def apply_portable(cfg: dict, body: dict) -> dict:
    if "gutter" in body and body["gutter"]:
        cfg["gutter"] = str(body["gutter"]).strip()
    if "start_dir" in body and body["start_dir"]:
        cfg["start_dir"] = str(body["start_dir"]).strip()
    if "title" in body:
        title = body["title"]
        cfg["title"] = None if title in (None, "") else str(title).strip()
    if "recent_max" in body:
        try:
            cfg["recent_max"] = max(1, min(24, int(body["recent_max"])))
        except (TypeError, ValueError):
            pass
    if "shortcuts" in body:
        raw = body["shortcuts"]
        if isinstance(raw, str):
            raw = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if isinstance(raw, list):
            cfg["shortcuts"] = [str(x).strip() for x in raw if str(x).strip()]
    if "skip_dirs" in body:
        raw = body["skip_dirs"]
        if isinstance(raw, str):
            raw = [ln.strip() for ln in raw.replace(",", "\n").splitlines() if ln.strip()]
        if isinstance(raw, list):
            cfg["skip_dirs"] = [str(x).strip() for x in raw if str(x).strip()]
    if "host" in body and body["host"]:
        cfg["host"] = str(body["host"]).strip()
    if "port" in body:
        try:
            cfg["port"] = max(1, min(65535, int(body["port"])))
        except (TypeError, ValueError):
            pass
    return cfg


def openai_request(url: str, api_key: str, payload: dict | None, method: str, timeout: int) -> dict:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("base URL must be http(s)")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "User-Agent": "MarkdownViewer/%s" % VERSION,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
            text = raw.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text) if text else {}
            except ValueError:
                parsed = {"raw": text[:400]}
            return {"ok": True, "status": getattr(resp, "status", 200), "data": parsed}
    except HTTPError as err:
        detail = ""
        try:
            detail = err.read(800).decode("utf-8", errors="replace")
        except OSError:
            detail = str(err)
        return {"ok": False, "status": err.code, "error": "HTTP %s" % err.code, "detail": detail[:400]}
    except (URLError, TimeoutError, OSError, ValueError) as err:
        return {"ok": False, "status": 0, "error": str(err), "detail": ""}


def looks_like_embed(name: str) -> bool:
    n = (name or "").lower()
    return any(token in n for token in ("embed", "bge-", "e5-", "gte-", "minilm"))


def pick_chat_model(provider: dict, requested: str = "") -> str:
    requested = (requested or "").strip()
    models = [str(m).strip() for m in (provider.get("models") or []) if str(m).strip()]
    if requested and not looks_like_embed(requested):
        return requested
    for name in models:
        if not looks_like_embed(name):
            return name
    if requested:
        return requested
    return models[0] if models else ""


def chat_complete(provider: dict, model: str, messages: list[dict], timeout: int = AI_TIMEOUT) -> dict:
    base = normalize_base_url(provider.get("base_url") or "")
    if not base:
        return {"ok": False, "error": "missing base URL"}
    model = pick_chat_model(provider, model)
    if not model:
        return {"ok": False, "error": "missing model"}
    if looks_like_embed(model):
        return {
            "ok": False,
            "error": "no chat model (the listed ids look like embedding models)",
            "detail": model,
        }
    result = openai_request(
        base + "/chat/completions",
        provider.get("api_key") or "",
        {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 4096,
        },
        "POST",
        timeout,
    )
    if not result.get("ok"):
        return result
    data = result.get("data") or {}
    choices = data.get("choices") if isinstance(data, dict) else None
    text = ""
    if isinstance(choices, list) and choices:
        msg = (choices[0] or {}).get("message") or {}
        text = msg.get("content") or ""
    if not text:
        return {"ok": False, "error": "empty model reply", "detail": str(data)[:400]}
    used = data.get("model") if isinstance(data, dict) else model
    return {"ok": True, "text": text, "model": used or model}


def list_remote_models(provider: dict, timeout: int = 20) -> dict:
    base = normalize_base_url(provider.get("base_url") or "")
    if not base:
        return {"ok": False, "error": "missing base URL", "models": []}
    result = openai_request(
        base + "/models",
        provider.get("api_key") or "",
        None,
        "GET",
        timeout,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "models failed", "models": [], "detail": result.get("detail") or ""}
    data = result.get("data") or {}
    rows = data.get("data") if isinstance(data, dict) else None
    names = []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                names.append(str(row["id"]))
            elif isinstance(row, str):
                names.append(row)
    return {"ok": True, "models": names[:200]}


def expand_dir(raw: str) -> Path:
    return Path(raw or "~").expanduser().resolve()


def pick_notes_dir(cli_root: str | None, cfg: dict) -> Path | None:
    """CLI folder wins; otherwise reopen last from config.local.json if it still exists."""
    if cli_root:
        path = Path(cli_root).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError("not a folder: %s" % path)
        return path
    last = str(cfg.get("last") or "").strip()
    if not last:
        return None
    try:
        path = expand_dir(last)
    except OSError:
        return None
    return path if path.is_dir() else None


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
        if is_system_name(name) or name in skip:
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

    def public_config(self) -> dict:
        with self.lock:
            return portable_public(self.cfg)

    def save_config(self, body: dict) -> dict:
        with self.lock:
            apply_portable(self.cfg, body)
            save_portable(self.cfg)
            save_local(self.cfg)
            gutter = self.cfg.get("gutter") or "1.75rem"
        return {"ok": True, "config": self.public_config(), "gutter": gutter}

    def public_ai(self) -> dict:
        with self.lock:
            ai = normalize_ai(self.cfg.get("ai") if isinstance(self.cfg.get("ai"), dict) else {})
        return redact_ai(ai)

    def save_ai(self, body: dict) -> dict:
        incoming = body.get("providers") if isinstance(body.get("providers"), dict) else {}
        with self.lock:
            current = normalize_ai(self.cfg.get("ai") if isinstance(self.cfg.get("ai"), dict) else {})
            old = current.get("providers") or {}
            merged = {}
            for key, value in incoming.items():
                pid = provider_id(str(key))
                if not isinstance(value, dict):
                    continue
                merged[pid] = normalize_provider(pid, value, old.get(pid))
            default = provider_id(str(body.get("default_provider") or current.get("default_provider") or ""))
            if default not in merged:
                default = next(iter(merged), "")
            self.cfg["ai"] = {"default_provider": default, "providers": merged}
            save_local(self.cfg)
        return {"ok": True, "ai": self.public_ai()}

    def provider(self, pid: str) -> dict | None:
        with self.lock:
            ai = normalize_ai(self.cfg.get("ai") if isinstance(self.cfg.get("ai"), dict) else {})
            return (ai.get("providers") or {}).get(provider_id(pid))

    def default_provider(self) -> dict | None:
        with self.lock:
            ai = normalize_ai(self.cfg.get("ai") if isinstance(self.cfg.get("ai"), dict) else {})
        providers = ai.get("providers") or {}
        pid = ai.get("default_provider") or ""
        if pid and pid in providers:
            return providers[pid]
        return next(iter(providers.values()), None)

    def read_note(self, rel: str) -> tuple[Path, str]:
        with self.lock:
            notes_dir = self.notes_dir
            skip = self.skip()
        if notes_dir is None:
            raise ValueError("no folder open")
        path = Path(rel or "")
        if not is_safe(notes_dir, path, skip):
            raise ValueError("not a note in this folder")
        full = (notes_dir / path).resolve()
        if not full.is_file():
            raise ValueError("missing note")
        text = full.read_text(encoding="utf-8")
        if len(text) > NOTE_MAX_CHARS:
            text = text[:NOTE_MAX_CHARS]
        return full, text

    def write_note(self, rel: str, text: str, overwrite: bool) -> dict:
        with self.lock:
            notes_dir = self.notes_dir
            skip = self.skip()
            title = self.title
        if notes_dir is None:
            raise ValueError("no folder open")
        rel_path = Path(rel or "")
        if rel_path.suffix.lower() not in MD_SUFFIXES:
            raise ValueError("save path must be markdown")
        if not is_safe(notes_dir, rel_path, skip):
            raise ValueError("not a path in this folder")
        full = (notes_dir / rel_path).resolve()
        if full.exists() and not overwrite:
            raise FileExistsError("already exists")
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text if isinstance(text, str) else "", encoding="utf-8")
        notes = list_notes(notes_dir, title, skip)
        return {
            "ok": True,
            "path": rel_path.as_posix(),
            "defaultDoc": default_doc(notes),
            "notes": notes,
        }

    def _known_paths(self) -> tuple[Path, str, set[str]]:
        with self.lock:
            notes_dir = self.notes_dir
            title = self.title
            skip = self.skip()
        if notes_dir is None:
            raise ValueError("no folder open")
        notes = list_notes(notes_dir, title, skip)
        return notes_dir, title, {n["path"] for n in notes}

    def public_memory(self) -> dict:
        with self.lock:
            notes_dir = self.notes_dir
        if notes_dir is None:
            raise ValueError("no folder open")
        mem_dir = resolve_memory_dir(notes_dir)
        prefix = memory_prefix(notes_dir, mem_dir)
        mem = load_memory(notes_dir)
        docs = {}
        for path, doc in (mem.get("docs") or {}).items():
            if not isinstance(doc, dict):
                continue
            local = from_memory_key(prefix, path)
            if local:
                docs[local] = public_doc(doc, prefix)
        topics_out = {}
        for term, paths in (mem.get("topics") or {}).items():
            local_paths = expose_paths(list(paths or []), prefix)
            if local_paths:
                topics_out[term] = local_paths
        return {
            "ok": True,
            "file": MEMORY_NAME,
            "updated": mem.get("updated") or "",
            "docs": docs,
            "keywords": mem.get("keywords") or [],
            "topics": topics_out,
        }

    def visit_note(self, rel: str) -> dict:
        rel_posix = Path(rel or "").as_posix()
        if Path(rel_posix).name == MEMORY_NAME or is_system_name(Path(rel_posix).name):
            raise ValueError("not a note")
        if Path(rel_posix).suffix.lower() not in MD_SUFFIXES:
            raise ValueError("not a note")
        full, text = self.read_note(rel_posix)
        try:
            raw = full.read_bytes()
        except OSError as err:
            raise ValueError(str(err)) from err
        sha = sha256_bytes(raw)
        notes_dir, _title, known = self._known_paths()
        known.add(rel_posix)
        mem_dir = resolve_memory_dir(notes_dir)
        prefix = memory_prefix(notes_dir, mem_dir)
        mem_rel = to_memory_key(prefix, rel_posix)
        mem_known = {to_memory_key(prefix, p) for p in known}
        mem_known.add(mem_rel)
        with self.lock:
            mem = load_memory(notes_dir)
            doc, fresh = apply_visit(mem, mem_rel, text, sha, len(raw), mem_known, prefix)
            wrote = save_memory(notes_dir, mem)
            folder_keys = list(mem.get("keywords") or [])
            topics = dict(mem.get("topics") or {})
        return {
            "ok": True,
            "wrote": wrote,
            "fresh": fresh,
            "path": rel_posix,
            "doc": public_doc(doc, prefix),
            "keywords": folder_keys,
            "topics": topics,
        }

    def enrich_note(self, rel: str, provider: dict | None, model: str) -> dict:
        visited = self.visit_note(rel)
        doc = visited.get("doc") or {}
        if doc.get("rich") and doc.get("tldr"):
            visited["enriched"] = False
            return visited
        if not provider or not provider.get("base_url"):
            visited["error"] = "save an AI provider first"
            return visited
        spec = prompt_by_id("memory-pack")
        if spec is None:
            visited["error"] = "missing memory-pack prompt"
            return visited
        _full, note = self.read_note(visited["path"])
        messages = [
            {"role": "system", "content": spec.get("system") or DEFAULT_PROMPT_SYSTEM},
            {
                "role": "user",
                "content": render_prompt(
                    spec.get("user") or "{{note}}",
                    note,
                    "",
                    format_keywords_for_prompt(doc.get("keywords") or []),
                ),
            },
        ]
        result = chat_complete(provider, model, messages)
        if not result.get("ok"):
            visited["error"] = result.get("error") or "enrich failed"
            visited["detail"] = result.get("detail") or ""
            return visited
        pack = parse_json_object(result.get("text") or "")
        if not pack:
            visited["error"] = "model did not return JSON cards"
            return visited
        with self.lock:
            notes_dir = self.notes_dir
            if notes_dir is None:
                visited["error"] = "no folder open"
                return visited
            mem = load_memory(notes_dir)
            mem_dir = resolve_memory_dir(notes_dir)
            prefix = memory_prefix(notes_dir, mem_dir)
            mem_rel = to_memory_key(prefix, visited["path"])
            current = (mem.get("docs") or {}).get(mem_rel)
            if not isinstance(current, dict) or current.get("sha256") != doc.get("sha256"):
                visited["error"] = "note changed during enrich"
                return visited
            updated = apply_pack(current, pack)
            mem.setdefault("docs", {})[mem_rel] = updated
            rebuild_folder_index(mem)
            wrote = save_memory(notes_dir, mem)
            folder_keys = list(mem.get("keywords") or [])
            topics = dict(mem.get("topics") or {})
        visited["doc"] = public_doc(updated, prefix)
        visited["wrote"] = wrote
        visited["enriched"] = True
        visited["keywords"] = folder_keys
        visited["topics"] = topics
        visited["model"] = result.get("model") or ""
        return visited

    def _chat_context(self, rel: str) -> tuple[Path, str, str, dict, list[dict]]:
        rel_posix = Path(rel or "").as_posix()
        if Path(rel_posix).name == MEMORY_NAME or is_system_name(Path(rel_posix).name):
            raise ValueError("not a note")
        if Path(rel_posix).suffix.lower() not in MD_SUFFIXES:
            raise ValueError("not a note")
        full, text = self.read_note(rel_posix)
        try:
            sha = sha256_bytes(full.read_bytes())
        except OSError as err:
            raise ValueError(str(err)) from err
        with self.lock:
            notes_dir = self.notes_dir
            if notes_dir is None:
                raise ValueError("no folder open")
            mem = load_memory(notes_dir)
            prev = (mem.get("docs") or {}).get(rel_posix)
            path = chat_path(notes_dir, rel_posix)
        doc = prev if isinstance(prev, dict) and prev.get("sha256") == sha else {}
        if not doc:
            doc = {
                "title": extract_title(text, Path(rel_posix).stem.replace("-", " ")),
                "headings": extract_headings(text),
                "keywords": [],
                "tldr": [],
            }
        return path, rel_posix, sha, doc, load_chat(path)

    def get_chat(self, rel: str) -> dict:
        path, rel_posix, sha, _doc, rows = self._chat_context(rel)
        changed = bool(rows) and last_snapshot_sha(rows) not in ("", sha)
        rel_file = Path(CHAT_DIR, Path(rel_posix).with_name(Path(rel_posix).name + ".jsonl"))
        return {
            "ok": True,
            "path": rel_posix,
            "file": rel_file.as_posix(),
            "note_sha": sha,
            "note_changed": changed,
            "messages": [public_chat_message(row) for row in rows],
        }

    def send_chat(
        self,
        rel: str,
        preset: str,
        extra: str,
        provider: dict | None,
        model: str,
        retry_id: str = "",
        edit_id: str = "",
    ) -> dict:
        spec = prompt_by_id(preset or "ask") or {
            "id": "ask",
            "system": CHAT_SYSTEM,
            "user": "{{prompt}}",
        }
        path, rel_posix, sha, doc, rows = self._chat_context(rel)
        if edit_id:
            idx = next((i for i, row in enumerate(rows) if row.get("id") == edit_id), -1)
            if idx < 0:
                raise ValueError("unknown chat message")
            if rows[idx].get("role") != "user":
                raise ValueError("can only edit a question")
            user_text = (extra or "").strip()
            if not user_text:
                raise ValueError("write a question")
            rows = list(rows[: idx + 1])
            updated = dict(rows[-1])
            updated["text"] = user_text
            updated["ts"] = utc_now()
            rows[-1] = updated
            extra = user_text
            preset = str(updated.get("preset") or preset or "ask")
            spec = prompt_by_id(preset) or spec
        elif retry_id:
            idx = next((i for i, row in enumerate(rows) if row.get("id") == retry_id), -1)
            if idx < 0:
                raise ValueError("unknown chat message")
            if rows[idx].get("role") != "assistant":
                raise ValueError("can only retry an assistant reply")
            user_idx = idx - 1
            while user_idx >= 0 and rows[user_idx].get("role") != "user":
                user_idx -= 1
            if user_idx < 0:
                raise ValueError("no user prompt to retry")
            rows = rows[: user_idx + 1]
            extra = str(rows[user_idx].get("text") or extra)
            preset = str(rows[user_idx].get("preset") or preset or "ask")
            spec = prompt_by_id(preset) or spec
        else:
            user_text = chat_user_text(spec, extra)
            if not user_text:
                raise ValueError("write a question")
            user_row = {
                "id": new_chat_id(),
                "ts": utc_now(),
                "role": "user",
                "kind": "preset" if (preset and preset != "ask") else "chat",
                "text": user_text,
                "preset": preset or "ask",
                "note_sha": sha,
                "ok": True,
            }
            rows = list(rows)
            rows.append(user_row)
        prev_sha = last_snapshot_sha(rows[:-1] if not retry_id else rows[: max(0, len(rows) - 1)])
        attach_note = prev_sha != sha
        if attach_note:
            snap = {
                "id": new_chat_id(),
                "ts": utc_now(),
                "role": "system",
                "kind": "note_changed" if prev_sha else "note_snapshot",
                "text": "Note updated. Chat kept." if prev_sha else "Using the current note.",
                "note_sha": sha,
                "ok": True,
            }
            insert_at = len(rows) - 1 if rows and rows[-1].get("role") == "user" else len(rows)
            rows.insert(insert_at, snap)
        history_src = [row for row in rows if row.get("role") in ("user", "assistant")]
        if history_src and history_src[-1].get("role") == "user":
            history_src = history_src[:-1]
        user_text = extra
        if rows and rows[-1].get("role") == "user":
            user_text = str(rows[-1].get("text") or extra)
        elif retry_id:
            user_text = extra
        _full, body = self.read_note(rel_posix)
        briefing = compact_briefing(rel_posix, sha, body, doc)
        messages = build_chat_messages(
            spec,
            briefing,
            body,
            history_for_model(history_src),
            user_text,
            attach_note,
        )
        if not provider or not provider.get("base_url"):
            raise ValueError("save an AI provider first")
        result = chat_complete(provider, model, messages)
        asst = {
            "id": new_chat_id(),
            "ts": utc_now(),
            "role": "assistant",
            "kind": "chat",
            "text": result.get("text") or "",
            "preset": preset or "ask",
            "model": result.get("model") or "",
            "note_sha": sha,
            "ok": bool(result.get("ok")),
            "error": "" if result.get("ok") else str(result.get("error") or "chat failed"),
        }
        if not result.get("ok"):
            asst["text"] = asst["error"]
        rows.append(asst)
        wrote = write_chat(path, rows)
        out = {
            "ok": bool(result.get("ok")),
            "wrote": wrote,
            "path": rel_posix,
            "attached_note": attach_note,
            "note_sha": sha,
            "messages": [public_chat_message(row) for row in rows],
            "id": asst["id"],
            "text": asst["text"],
            "model": asst["model"],
        }
        if not result.get("ok"):
            out["error"] = asst["error"]
            out["detail"] = result.get("detail") or ""
        return out


def make_handler(app_dir: Path, state: AppState):
    api_get = {
        "/api/notes",
        "/api/preview",
        "/api/fs",
        "/api/state",
        "/api/config",
        "/api/ai",
        "/api/memory",
        "/api/chat",
    }
    api_post = {
        "/api/open",
        "/api/config",
        "/api/ai",
        "/api/ai/test",
        "/api/ai/models",
        "/api/ai/run",
        "/api/ai/save",
        "/api/memory/visit",
        "/api/memory/enrich",
        "/api/chat",
        "/api/chat/retry",
        "/api/chat/edit",
    }
    api_all = api_get | api_post

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

        def _read_json_body(self, max_bytes: int) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            if length < 0 or length > max_bytes:
                raise ValueError("bad request")
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                body = json.loads(raw) if raw else {}
            except ValueError as err:
                raise ValueError("invalid json") from err
            if not isinstance(body, dict):
                raise ValueError("invalid json")
            return body

        def _need_local(self) -> bool:
            if self._local():
                return True
            self._send_json({"error": "localhost only"}, 403)
            return False

        def _provider_from_body(self, body: dict) -> dict | None:
            pid = str(body.get("provider") or body.get("id") or "")
            live = dict(body)
            stored = state.provider(pid) if pid else None
            if stored:
                return normalize_provider(provider_id(pid), live, stored)
            if live.get("base_url"):
                return normalize_provider(provider_id(pid or "custom"), live, None)
            return state.default_provider()

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
            if parsed.path == "/api/config":
                if not self._need_local():
                    return
                self._send_json(state.public_config())
                return
            if parsed.path == "/api/ai":
                if not self._need_local():
                    return
                self._send_json(state.public_ai())
                return
            if parsed.path == "/api/memory":
                if not self._need_local():
                    return
                try:
                    self._send_json(state.public_memory())
                except ValueError as err:
                    self._send_json({"error": str(err)}, 409)
                return
            if parsed.path == "/api/chat":
                if not self._need_local():
                    return
                rel = (parse_qs(parsed.query).get("path") or [""])[0]
                try:
                    self._send_json(state.get_chat(rel))
                except ValueError as err:
                    self._send_json({"ok": False, "error": str(err), "messages": []}, 400)
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
            path = parsed.path
            if path not in api_post:
                self.send_error(404, "Not found")
                return
            if not self._need_local():
                return
            max_bytes = 200_000 if path == "/api/ai/save" else 80_000
            try:
                body = self._read_json_body(max_bytes)
            except ValueError as err:
                self._send_json({"error": str(err)}, 400)
                return
            if path == "/api/open":
                folder = body.get("path") or ""
                try:
                    self._send_json(state.open_folder(str(folder)))
                except (OSError, ValueError) as err:
                    self._send_json({"error": str(err)}, 400)
                return
            if path == "/api/config":
                try:
                    self._send_json(state.save_config(body))
                except OSError as err:
                    self._send_json({"error": str(err)}, 500)
                return
            if path == "/api/ai":
                try:
                    self._send_json(state.save_ai(body))
                except OSError as err:
                    self._send_json({"error": str(err)}, 500)
                return
            if path == "/api/ai/test":
                prov = self._provider_from_body(body)
                if not prov or not prov.get("base_url"):
                    self._send_json({"ok": False, "error": "pick a provider with a base URL"}, 400)
                    return
                model = pick_chat_model(prov, str(body.get("model") or ""))
                result = chat_complete(
                    prov,
                    model,
                    [{"role": "user", "content": "Reply with the single word pong."}],
                    timeout=25,
                )
                self._send_json(result, 200 if result.get("ok") else 502)
                return
            if path == "/api/ai/models":
                prov = self._provider_from_body(body)
                if not prov or not prov.get("base_url"):
                    self._send_json({"ok": False, "error": "pick a provider with a base URL", "models": []}, 400)
                    return
                self._send_json(list_remote_models(prov))
                return
            if path == "/api/ai/run":
                rel = str(body.get("path") or "")
                preset = str(body.get("preset") or "")
                extra = str(body.get("prompt") or "").strip()
                spec = prompt_by_id(preset)
                if spec is None:
                    self._send_json({"ok": False, "error": "unknown prompt (add a json file under ai/prompts)"}, 400)
                    return
                if "{{prompt}}" in (spec.get("user") or "") and not extra:
                    self._send_json({"ok": False, "error": "write a prompt for this catalog item"}, 400)
                    return
                prov = self._provider_from_body(body)
                if not prov or not prov.get("base_url"):
                    self._send_json({"ok": False, "error": "save an AI provider first"}, 400)
                    return
                try:
                    _full, note = state.read_note(rel)
                except (OSError, ValueError) as err:
                    self._send_json({"ok": False, "error": str(err)}, 400)
                    return
                messages = [
                    {
                        "role": "system",
                        "content": spec.get("system") or DEFAULT_PROMPT_SYSTEM,
                    },
                    {
                        "role": "user",
                        "content": render_prompt(spec.get("user") or "{{note}}", note, extra),
                    },
                ]
                result = chat_complete(prov, str(body.get("model") or ""), messages)
                result["path"] = rel
                self._send_json(result, 200 if result.get("ok") else 502)
                return
            if path == "/api/memory/visit":
                rel = str(body.get("path") or "")
                try:
                    self._send_json(state.visit_note(rel))
                except (OSError, ValueError) as err:
                    self._send_json({"ok": False, "error": str(err)}, 400)
                return
            if path == "/api/chat":
                rel = str(body.get("path") or "")
                preset = str(body.get("preset") or "ask")
                extra = str(body.get("prompt") or "").strip()
                prov = self._provider_from_body(body) or state.default_provider()
                try:
                    result = state.send_chat(rel, preset, extra, prov, str(body.get("model") or ""))
                except (OSError, ValueError) as err:
                    self._send_json({"ok": False, "error": str(err), "messages": []}, 400)
                    return
                self._send_json(result, 200 if result.get("ok") else 502)
                return
            if path == "/api/chat/retry":
                rel = str(body.get("path") or "")
                retry_id = str(body.get("id") or "")
                prov = self._provider_from_body(body) or state.default_provider()
                try:
                    result = state.send_chat(
                        rel, "ask", "", prov, str(body.get("model") or ""), retry_id=retry_id
                    )
                except (OSError, ValueError) as err:
                    self._send_json({"ok": False, "error": str(err), "messages": []}, 400)
                    return
                self._send_json(result, 200 if result.get("ok") else 502)
                return
            if path == "/api/chat/edit":
                rel = str(body.get("path") or "")
                edit_id = str(body.get("id") or "")
                extra = str(body.get("prompt") or "").strip()
                prov = self._provider_from_body(body) or state.default_provider()
                try:
                    result = state.send_chat(
                        rel,
                        "ask",
                        extra,
                        prov,
                        str(body.get("model") or ""),
                        edit_id=edit_id,
                    )
                except (OSError, ValueError) as err:
                    self._send_json({"ok": False, "error": str(err), "messages": []}, 400)
                    return
                self._send_json(result, 200 if result.get("ok") else 502)
                return
            if path == "/api/memory/enrich":
                rel = str(body.get("path") or "")
                prov = self._provider_from_body(body) or state.default_provider()
                try:
                    result = state.enrich_note(rel, prov, str(body.get("model") or ""))
                except (OSError, ValueError) as err:
                    self._send_json({"ok": False, "error": str(err)}, 400)
                    return
                status = 200
                if result.get("error") and not result.get("doc"):
                    status = 400
                self._send_json(result, status)
                return
            if path == "/api/ai/save":
                rel = str(body.get("path") or "")
                text = body.get("text")
                if not isinstance(text, str):
                    self._send_json({"ok": False, "error": "missing text"}, 400)
                    return
                overwrite = bool(body.get("overwrite"))
                try:
                    self._send_json(state.write_note(rel, text, overwrite))
                except FileExistsError:
                    self._send_json({"ok": False, "error": "already exists", "path": rel}, 409)
                except (OSError, ValueError) as err:
                    self._send_json({"ok": False, "error": str(err)}, 400)
                return

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("%s — %s\n" % (self.address_string(), fmt % args))

    return Handler


def bind_http_server(host: str, port: int, handler, tries: int = 20):
    last_err: OSError | None = None
    for offset in range(max(1, tries)):
        candidate = port + offset
        try:
            return ThreadingHTTPServer((host, candidate), handler), candidate
        except OSError as err:
            last_err = err
    raise OSError("could not bind %s:%s (%s)" % (host, port, last_err))


def setup_frozen_log() -> None:
    if not getattr(sys, "frozen", False):
        return
    log = user_data_dir() / "viewer.log"
    handle = open(log, "a", encoding="utf-8", buffering=1)
    sys.stdout = handle
    sys.stderr = handle


def fatal_dialog(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
    if not getattr(sys, "frozen", False):
        return
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Markdown Viewer", 0x10)
        except Exception:
            return


def open_browser(url: str) -> None:
    def _open() -> None:
        time.sleep(0.45)
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_open, name="mdview-browser", daemon=True).start()


def run_status_window(url: str, httpd: ThreadingHTTPServer) -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped", flush=True)
        return 0

    root = tk.Tk()
    root.title("Markdown Viewer")
    root.resizable(False, False)
    icon = APP_DIR / "icons" / "app.png"
    if icon.is_file():
        try:
            photo = tk.PhotoImage(file=str(icon))
            root.iconphoto(True, photo)
            root._icon = photo
        except Exception:
            pass
    pad = ttk.Frame(root, padding=16)
    pad.grid(row=0, column=0)
    ttk.Label(pad, text="Markdown Viewer v%s" % VERSION).grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(pad, text=url).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 12))

    def open_site() -> None:
        open_browser(url)

    def quit_app() -> None:
        threading.Thread(target=httpd.shutdown, name="mdview-stop", daemon=True).start()
        root.destroy()

    ttk.Button(pad, text="Open in browser", command=open_site).grid(row=2, column=0, padx=(0, 8))
    ttk.Button(pad, text="Quit", command=quit_app).grid(row=2, column=1)
    root.protocol("WM_DELETE_WINDOW", quit_app)
    root.mainloop()
    return 0


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
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open the viewer in a web browser (always on for the .app / .exe)",
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Do not show the small desktop status window",
    )
    args = parser.parse_args()
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        setup_frozen_log()

    cfg = load_config()
    if args.host:
        cfg["host"] = args.host
    if args.port is not None:
        cfg["port"] = args.port
    if args.title:
        cfg["title"] = args.title

    try:
        notes_dir = pick_notes_dir(args.root, cfg)
    except FileNotFoundError as err:
        fatal_dialog(str(err))
        return 2

    title = cfg.get("title")
    state = AppState(cfg, notes_dir, title)
    host = str(cfg.get("host") or "127.0.0.1")
    port = int(cfg.get("port") or 8765)
    handler = make_handler(APP_DIR, state)
    try:
        httpd, port = bind_http_server(host, port, handler)
    except OSError as err:
        fatal_dialog(str(err))
        return 1
    url = "http://%s:%s" % (host, port)
    print("Markdown viewer %s" % VERSION, flush=True)
    print("  config  %s" % CONFIG_PATH, flush=True)
    if yake_lib is None:
        print("  keywords  stdlib fallback (pip install -r requirements.txt for YAKE)", flush=True)
    else:
        print("  keywords  yake", flush=True)
    if notes_dir:
        print("  folder  %s" % notes_dir, flush=True)
    else:
        print("  pick a folder at %s" % url, flush=True)
    print("  %s" % url, flush=True)
    print("  Ctrl-C to stop", flush=True)
    want_browser = (frozen or args.browser) and not args.no_browser
    want_gui = frozen and not args.no_gui
    if want_browser:
        open_browser(url)
    if want_gui:
        worker = threading.Thread(target=httpd.serve_forever, name="mdview-http", daemon=True)
        worker.start()
        return run_status_window(url, httpd)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        import multiprocessing

        multiprocessing.freeze_support()
    raise SystemExit(main())
