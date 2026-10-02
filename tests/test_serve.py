#!/usr/bin/env python3
"""Unit tests for serve.py. Stdlib only — no pip.

    python3 -m unittest discover -s tests
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "notes"


def load_serve():
    spec = importlib.util.spec_from_file_location("mdview_serve", ROOT / "serve.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mdview_serve"] = mod
    spec.loader.exec_module(mod)
    return mod


serve = load_serve()


class DefaultDocTests(unittest.TestCase):
    def test_readme_wins(self):
        notes = [
            {"path": "atlas/one.md"},
            {"path": "README.md"},
            {"path": "blogs/two.md"},
        ]
        self.assertEqual(serve.default_doc(notes), "README.md")

    def test_first_note_when_no_readme(self):
        notes = [{"path": "ATLAS_2.0.0.md"}, {"path": "HOW_ZEUS.md"}]
        self.assertEqual(serve.default_doc(notes), "ATLAS_2.0.0.md")

    def test_empty(self):
        self.assertEqual(serve.default_doc([]), "")


class DesktopPackagingTests(unittest.TestCase):
    def test_dev_paths_are_the_repo(self):
        self.assertEqual(serve.bundled_dir(), ROOT)
        self.assertEqual(serve.APP_DIR, ROOT)
        self.assertEqual(serve.CONFIG_PATH, ROOT / "config.json")

    def test_frozen_bundled_dir_uses_meipass(self):
        old_frozen = getattr(sys, "frozen", None)
        old_meipass = getattr(sys, "_MEIPASS", None)
        try:
            sys.frozen = True
            sys._MEIPASS = str(Path("/tmp/mdview-meipass"))
            self.assertEqual(serve.bundled_dir(), Path("/tmp/mdview-meipass"))
        finally:
            if old_frozen is None:
                delattr(sys, "frozen")
            else:
                sys.frozen = old_frozen
            if old_meipass is None and hasattr(sys, "_MEIPASS"):
                delattr(sys, "_MEIPASS")
            elif old_meipass is not None:
                sys._MEIPASS = old_meipass

    def test_bind_http_server_falls_back_when_port_busy(self):
        busy = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        port = busy.server_address[1]
        try:
            httpd, used = serve.bind_http_server("127.0.0.1", port, BaseHTTPRequestHandler, tries=5)
            try:
                self.assertNotEqual(used, port)
                self.assertGreater(used, port)
            finally:
                httpd.server_close()
        finally:
            busy.server_close()


class ListNotesTests(unittest.TestCase):
    def test_fixture_groups(self):
        notes = serve.list_notes(FIXTURES, "notes")
        paths = {n["path"] for n in notes}
        self.assertIn("README.md", paths)
        self.assertIn("atlas/one.md", paths)
        self.assertIn("blogs/two.md", paths)
        self.assertIn("blogs/three.md", paths)
        groups = {n["path"]: n["group"] for n in notes}
        self.assertEqual(groups["README.md"], "notes")
        self.assertEqual(groups["atlas/one.md"], "atlas")
        self.assertEqual(groups["blogs/two.md"], "blogs")

    def test_skips_git_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "keep.md").write_text("# Keep\n", encoding="utf-8")
            git = root / ".git"
            git.mkdir()
            (git / "hidden.md").write_text("# Hidden\n", encoding="utf-8")
            notes = serve.list_notes(root, "tmp")
            paths = {n["path"] for n in notes}
            self.assertEqual(paths, {"keep.md"})


class SafetyTests(unittest.TestCase):
    def test_inside_ok(self):
        self.assertTrue(serve.is_safe(FIXTURES, Path("README.md")))
        self.assertTrue(serve.is_safe(FIXTURES, Path("atlas/one.md")))

    def test_escape_rejected(self):
        self.assertFalse(serve.is_safe(FIXTURES, Path("../serve.py")))

    def test_skip_dir_rejected(self):
        self.assertFalse(serve.is_safe(FIXTURES, Path(".git/config")))


class MemoryKeywordTests(unittest.TestCase):
    def test_counts_phrases_and_drops_stopwords(self):
        text = """# Patient care with xyz drug

The xyz drug is used in patient care. The xyz drug helps.
Patient care requires the xyz drug. The and a of to.
"""
        rows = serve.keyword_counts(text)
        terms = {row[0]: row[1] for row in rows}
        self.assertNotIn("the", terms)
        self.assertNotIn("and", terms)
        self.assertIn("xyz drug", terms)
        self.assertIn("patient care", terms)
        self.assertNotIn("xyz", terms)
        self.assertNotIn("drug", terms)
        self.assertNotIn("patient", terms)
        self.assertNotIn("care", terms)
        self.assertLessEqual(len(rows), serve.DOC_KEYWORD_MAX)
        self.assertTrue(rows[0][1] >= rows[-1][1])
        for term, n in rows:
            self.assertGreaterEqual(len(str(term).split()), serve.KEYWORD_MIN_WORDS)
            self.assertGreaterEqual(n, serve.KEYWORD_MIN_COUNT)

    def test_skips_fenced_code(self):
        text = """# Hello

```
ripe banana ripe banana ripe banana ripe banana
```

ripe banana ripe banana ripe banana shows in the body.
"""
        terms = {row[0]: row[1] for row in serve.keyword_counts(text)}
        self.assertIn("ripe banana", terms)
        self.assertEqual(terms["ripe banana"], 3)

    def test_drops_unigrams_and_low_counts(self):
        text = """# Hello

xyz drug xyz drug xyz drug xyz drug
solo solo solo solo
once pair
twice pair twice pair
"""
        rows = serve.keyword_counts(text)
        terms = {row[0]: row[1] for row in rows}
        self.assertIn("xyz drug", terms)
        self.assertNotIn("xyz", terms)
        self.assertNotIn("drug", terms)
        self.assertNotIn("solo", terms)
        self.assertNotIn("once pair", terms)
        self.assertNotIn("twice pair", terms)
        for term, n in rows:
            self.assertGreaterEqual(len(str(term).split()), 2)
            self.assertGreaterEqual(n, 3)

    def test_heading_weight(self):
        text = "# Unique heading phrase\n\nbody word body word\n"
        terms = {row[0]: row[1] for row in serve.keyword_counts(text)}
        phrase_hits = [
            terms.get("unique heading"),
            terms.get("heading phrase"),
            terms.get("unique heading phrase"),
        ]
        self.assertTrue(any((n or 0) >= 3 for n in phrase_hits), terms)
        self.assertNotIn("uniqueheadingword", terms)

    def test_local_links(self):
        text = "See [two](two.md) and [skip](https://example.com/a.md).\n"
        known = {"blogs/two.md", "README.md", "two.md"}
        links = serve.extract_local_links(text, "README.md", known)
        self.assertEqual(links, ["two.md"])

    def test_parse_pack_json(self):
        raw = '```json\n{"tldr":["a","b","c"],"next_action":"go","important":"keep","topics":["x"]}\n```'
        pack = serve.parse_json_object(raw)
        self.assertEqual(pack["next_action"], "go")
        self.assertEqual(pack["tldr"][0], "a")

    def test_visit_writes_memory_and_hash_skip(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            old_local = serve.LOCAL_PATH
            serve.LOCAL_PATH = Path(raw) / "config.local.json"
            note = root / "hello.md"
            note.write_text("# Hello xyz drug\n\nThe xyz drug is mentioned. xyz drug again.\n", encoding="utf-8")
            cfg = dict(serve.DEFAULT_CONFIG)
            try:
                state = serve.AppState(cfg, root, "tmp")
                first = state.visit_note("hello.md")
                self.assertTrue(first["ok"])
                self.assertTrue(first["fresh"])
                self.assertTrue((root / serve.MEMORY_NAME).is_file())
                terms = {row[0]: row[1] for row in first["doc"]["keywords"]}
                self.assertIn("xyz drug", terms)
                second = state.visit_note("hello.md")
                self.assertFalse(second["fresh"])
                self.assertEqual(second["doc"]["visits"], 2)
                self.assertEqual(second["doc"]["sha256"], first["doc"]["sha256"])
                note.write_text("# Hello xyz drug\n\nChanged body about patient care patient care.\n", encoding="utf-8")
                third = state.visit_note("hello.md")
                self.assertTrue(third["fresh"])
                self.assertNotEqual(third["doc"]["sha256"], first["doc"]["sha256"])
            finally:
                serve.LOCAL_PATH = old_local

    def test_nested_folder_reuses_parent_memory(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            old_local = serve.LOCAL_PATH
            serve.LOCAL_PATH = Path(raw) / "config.local.json"
            (root / "root-note.md").write_text(
                "# Root note\n\nThe xyz drug is used. The xyz drug helps patient care patient care.\n",
                encoding="utf-8",
            )
            sub = root / "nested"
            sub.mkdir()
            (sub / "child.md").write_text(
                "# Child note\n\nThe xyz drug is used. The xyz drug helps patient care patient care.\n",
                encoding="utf-8",
            )
            cfg = dict(serve.DEFAULT_CONFIG)
            try:
                parent = serve.AppState(cfg, root, "tmp")
                parent.visit_note("root-note.md")
                self.assertTrue((root / serve.MEMORY_NAME).is_file())
                child_state = serve.AppState(dict(serve.DEFAULT_CONFIG), sub, "nested")
                got = child_state.visit_note("child.md")
                self.assertTrue(got["ok"])
                self.assertEqual(got["path"], "child.md")
                pointer = json.loads((sub / serve.MEMORY_NAME).read_text(encoding="utf-8"))
                self.assertEqual(pointer.get("ref"), "..")
                self.assertNotIn("docs", pointer)
                store = json.loads((root / serve.MEMORY_NAME).read_text(encoding="utf-8"))
                self.assertIn("root-note.md", store["docs"])
                self.assertIn("nested/child.md", store["docs"])
                self.assertNotIn("child.md", store["docs"])
            finally:
                serve.LOCAL_PATH = old_local

    def test_nested_visit_does_not_prune_sibling_docs(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            old_local = serve.LOCAL_PATH
            serve.LOCAL_PATH = Path(raw) / "config.local.json"
            (root / "keep.md").write_text(
                "# Keep\n\nThe xyz drug is used. The xyz drug helps patient care patient care.\n",
                encoding="utf-8",
            )
            other = root / "other"
            other.mkdir()
            (other / "gone.md").write_text("# Gone\n", encoding="utf-8")
            sub = root / "nested"
            sub.mkdir()
            (sub / "child.md").write_text(
                "# Child\n\nThe xyz drug is used. The xyz drug helps patient care patient care.\n",
                encoding="utf-8",
            )
            cfg = dict(serve.DEFAULT_CONFIG)
            try:
                parent = serve.AppState(cfg, root, "tmp")
                parent.visit_note("keep.md")
                store = json.loads((root / serve.MEMORY_NAME).read_text(encoding="utf-8"))
                store["docs"]["other/gone.md"] = {"sha256": "x", "keywords": []}
                (root / serve.MEMORY_NAME).write_text(
                    json.dumps(store, indent=2) + "\n", encoding="utf-8"
                )
                child_state = serve.AppState(dict(serve.DEFAULT_CONFIG), sub, "nested")
                child_state.visit_note("child.md")
                again = json.loads((root / serve.MEMORY_NAME).read_text(encoding="utf-8"))
                self.assertIn("keep.md", again["docs"])
                self.assertIn("other/gone.md", again["docs"])
                self.assertIn("nested/child.md", again["docs"])
            finally:
                serve.LOCAL_PATH = old_local

    def test_list_fs_hides_underscore(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "keep.md").write_text("# Keep\n", encoding="utf-8")
            (root / "_memory.json").write_text("{}", encoding="utf-8")
            hidden = root / "_secret"
            hidden.mkdir()
            (hidden / "nope.md").write_text("# No\n", encoding="utf-8")
            listing = serve.list_fs(root, set())
            names = [d["name"] for d in listing["dirs"]]
            files = [f["name"] for f in listing["files"]]
            self.assertNotIn("_secret", names)
            self.assertNotIn("_memory.json", files)
            self.assertIn("keep.md", files)

    def test_list_notes_skips_chats_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "keep.md").write_text("# Keep\n", encoding="utf-8")
            hidden = root / "_chats"
            hidden.mkdir()
            (hidden / "nope.md").write_text("# No\n", encoding="utf-8")
            notes = serve.list_notes(root, "tmp")
            paths = {n["path"] for n in notes}
            self.assertEqual(paths, {"keep.md"})


class PreviewTests(unittest.TestCase):
    def test_localhost_blocked(self):
        self.assertFalse(serve.preview_url_allowed("http://127.0.0.1/secret"))
        self.assertFalse(serve.preview_url_allowed("http://localhost/x"))
        self.assertFalse(serve.preview_url_allowed("file:///etc/passwd"))

    def test_parse_og(self):
        html = """
        <html><head>
          <meta property="og:title" content="Hello">
          <meta property="og:description" content="World">
        </head><body><p>ignored if og is set</p></body></html>
        """
        data = serve.parse_preview_html(html, "https://example.com/page")
        self.assertTrue(data["ok"])
        self.assertEqual(data["title"], "Hello")
        self.assertEqual(data["description"], "World")
        self.assertEqual(data["host"], "example.com")


class ShortcutTests(unittest.TestCase):
    def test_default_includes_downloads(self):
        self.assertIn("~/Downloads", serve.DEFAULT_CONFIG["shortcuts"])

    def test_downloads_badge_label(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            downs = root / "Downloads"
            downs.mkdir()
            items = serve.shortcut_items(
                {"shortcuts": [str(root / "missing"), str(downs)]}
            )
            self.assertEqual(items, [{"name": "Downloads", "path": str(downs.resolve())}])


class PickNotesDirTests(unittest.TestCase):
    def test_cli_wins(self):
        got = serve.pick_notes_dir(str(FIXTURES), {"last": "/no/such"})
        self.assertEqual(got, FIXTURES.resolve())

    def test_cli_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            serve.pick_notes_dir("/no/such/folder", {})

    def test_reopens_last(self):
        got = serve.pick_notes_dir(None, {"last": str(FIXTURES)})
        self.assertEqual(got, FIXTURES.resolve())

    def test_stale_last_is_none(self):
        self.assertIsNone(serve.pick_notes_dir(None, {"last": "/no/such/folder"}))

    def test_empty_is_none(self):
        self.assertIsNone(serve.pick_notes_dir(None, {"last": ""}))


class VersionTests(unittest.TestCase):
    def test_semver(self):
        parts = serve.VERSION.split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p.isdigit() for p in parts))


class HttpApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        serve.LOCAL_PATH = Path(cls.tmp.name) / "config.local.json"
        cfg = dict(serve.DEFAULT_CONFIG)
        cfg["recent"] = []
        cfg["last"] = ""
        state = serve.AppState(cfg, FIXTURES, None)
        handler = serve.make_handler(serve.APP_DIR, state)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = "http://127.0.0.1:%s" % cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def _json(self, path: str) -> dict:
        with urlopen(cls_url(self.base, path), timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_state_version_and_open(self):
        data = self._json("/api/state")
        self.assertEqual(data["version"], serve.VERSION)
        self.assertTrue(data["open"])
        self.assertTrue(data["path"].endswith("notes"))

    def test_notes_default_readme(self):
        data = self._json("/api/notes")
        self.assertEqual(data["defaultDoc"], "README.md")
        paths = [n["path"] for n in data["notes"]]
        self.assertIn("atlas/one.md", paths)
        self.assertIn("blogs/two.md", paths)

    def test_readme_body(self):
        with urlopen(cls_url(self.base, "/README.md"), timeout=5) as resp:
            body = resp.read().decode("utf-8")
        self.assertIn("Fixture notes", body)

    def test_missing_note_404(self):
        from urllib.error import HTTPError

        with self.assertRaises(HTTPError) as ctx:
            urlopen(cls_url(self.base, "/nope.md"), timeout=5)
        self.assertEqual(ctx.exception.code, 404)


def cls_url(base: str, path: str) -> str:
    return base + path


class AiHelperTests(unittest.TestCase):
    def test_strips_chat_completions(self):
        self.assertEqual(
            serve.normalize_base_url("https://api.x.ai/v1/chat/completions"),
            "https://api.x.ai/v1",
        )
        self.assertEqual(serve.normalize_base_url("http://127.0.0.1:11434/v1/"), "http://127.0.0.1:11434/v1")

    def test_mask_and_keep_key(self):
        prev = {"api_key": "secret-token", "label": "Grok", "base_url": "https://api.x.ai/v1", "models": ["grok-4"]}
        kept = serve.normalize_provider("grok", {"api_key": serve.AI_KEY_MASK, "label": "xAI"}, prev)
        self.assertEqual(kept["api_key"], "secret-token")
        rotated = serve.normalize_provider("grok", {"api_key": "new-key"}, prev)
        self.assertEqual(rotated["api_key"], "new-key")

    def test_skips_embed_models(self):
        prov = {"models": ["nomic-embed-text:latest", "llama3.2"]}
        self.assertEqual(serve.pick_chat_model(prov, ""), "llama3.2")
        self.assertTrue(serve.looks_like_embed("nomic-embed-text:latest"))

    def test_redact_hides_key(self):
        red = serve.redact_provider(
            {"id": "grok", "label": "Grok", "base_url": "https://api.x.ai/v1", "api_key": "sk-live", "models": []}
        )
        self.assertTrue(red["api_key_set"])
        self.assertEqual(red["api_key"], serve.AI_KEY_MASK)
        self.assertNotIn("sk-live", json.dumps(red))

    def test_prompt_catalog_files(self):
        rows = serve.load_prompts()
        ids = [r["id"] for r in rows]
        self.assertIn("summarize", ids)
        self.assertIn("ask", ids)
        self.assertIn("proofread", ids)
        ask = serve.prompt_by_id("ask")
        self.assertIsNotNone(ask)
        self.assertIn("{{prompt}}", ask["user"])
        rendered = serve.render_prompt(ask["user"], "# Note", "What is this?")
        self.assertIn("# Note", rendered)
        self.assertIn("What is this?", rendered)
        pub = serve.public_prompts()
        ask_pub = [p for p in pub if p["id"] == "ask"][0]
        self.assertTrue(ask_pub["requires_prompt"])
        self.assertNotIn("system", ask_pub)
        self.assertNotIn("user", ask_pub)
        self.assertIn("memory-pack", ids)
        self.assertTrue(serve.prompt_by_id("memory-pack").get("hidden"))
        self.assertNotIn("memory-pack", [p["id"] for p in pub])

    def test_hub_provider_catalog(self):
        rows = serve.load_provider_catalog()
        ids = [r["id"] for r in rows]
        self.assertEqual(
            ids,
            [
                "xai",
                "openai",
                "anthropic",
                "gemini",
                "azure_openai",
                "bedrock",
                "groq",
                "together",
                "fireworks",
                "mistral",
                "deepseek",
                "cohere",
                "perplexity",
                "openrouter",
                "ollama",
                "custom",
            ],
        )
        labels = [r["label"] for r in rows]
        self.assertIn("xAI (Grok)", labels)
        self.assertIn("Ollama (local)", labels)
        xai = [r for r in rows if r["id"] == "xai"][0]
        self.assertEqual(xai["suggested_id"], "grok")
        self.assertEqual(xai["base_url"], "https://api.x.ai/v1")


class ConfigAiHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._old_local = serve.LOCAL_PATH
        cls._old_config = serve.CONFIG_PATH
        serve.LOCAL_PATH = Path(cls.tmp.name) / "config.local.json"
        serve.CONFIG_PATH = Path(cls.tmp.name) / "config.json"
        notes = Path(cls.tmp.name) / "notes"
        notes.mkdir()
        (notes / "hello.md").write_text("# Hello\n\nBody.\n", encoding="utf-8")
        cfg = dict(serve.DEFAULT_CONFIG)
        cfg["recent"] = []
        cfg["last"] = ""
        cfg["ai"] = {"default_provider": "", "providers": {}}
        cls.notes = notes
        cls.state = serve.AppState(cfg, notes, None)
        handler = serve.make_handler(serve.APP_DIR, cls.state)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = "http://127.0.0.1:%s" % cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

        cls.fake_payloads = []

        class FakeAI(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def _json(self, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._json({"data": [{"id": "dummy-1"}, {"id": "dummy-2"}]})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except ValueError:
                    payload = {}
                cls.fake_payloads.append(payload)
                blob = json.dumps(payload)
                if "tldr" in blob or "memory-pack" in blob or "JSON only" in blob:
                    content = json.dumps(
                        {
                            "tldr": ["Hello claim", "Status draft", "Not a 1.0 claim"],
                            "next_action": "Open the other note",
                            "important": "Keep the source file",
                            "topics": ["hello"],
                        }
                    )
                else:
                    content = "pong from model. See [two](two.md) and ![img](pic.png)."
                self._json(
                    {
                        "model": "dummy-1",
                        "choices": [{"message": {"content": content}}],
                    }
                )

        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeAI)
        cls.fake_base = "http://127.0.0.1:%s/v1" % cls.fake.server_address[1]
        cls.fake_thread = threading.Thread(target=cls.fake.serve_forever, daemon=True)
        cls.fake_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.fake.shutdown()
        cls.fake.server_close()
        serve.LOCAL_PATH = cls._old_local
        serve.CONFIG_PATH = cls._old_config
        cls.tmp.cleanup()

    def _json(self, path, data=None, method="GET"):
        from urllib.request import Request

        if data is None:
            req = Request(self.base + path, method=method)
        else:
            raw = json.dumps(data).encode("utf-8")
            req = Request(
                self.base + path,
                data=raw,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
        with urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status

    def test_ai_get_has_catalog_no_secret(self):
        data, status = self._json("/api/ai")
        self.assertEqual(status, 200)
        ids = [row["id"] for row in data["catalog"]]
        self.assertIn("xai", ids)
        self.assertIn("openai", ids)
        self.assertIn("anthropic", ids)
        self.assertIn("ollama", ids)
        self.assertIn("openrouter", ids)
        self.assertIn("custom", ids)
        self.assertIn("providers", data)
        prompt_ids = [row["id"] for row in data["prompts"]]
        self.assertIn("summarize", prompt_ids)
        self.assertIn("ask", prompt_ids)
        self.assertNotIn("memory-pack", prompt_ids)
        ask = [p for p in data["prompts"] if p["id"] == "ask"][0]
        self.assertTrue(ask["requires_prompt"])
        self.assertNotIn("system", ask)

    def test_save_provider_keeps_key_on_mask(self):
        payload = {
            "default_provider": "local",
            "providers": {
                "local": {
                    "label": "Dummy",
                    "base_url": self.fake_base,
                    "api_key": "super-secret",
                    "models": ["dummy-1"],
                    "service": "custom",
                }
            },
        }
        data, status = self._json("/api/ai", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["ai"]["providers"]["local"]["api_key_set"])
        self.assertNotIn("super-secret", json.dumps(data))
        again, _ = self._json(
            "/api/ai",
            {
                "default_provider": "local",
                "providers": {
                    "local": {
                        "label": "Dummy",
                        "base_url": self.fake_base,
                        "api_key": serve.AI_KEY_MASK,
                        "models": ["dummy-1"],
                        "service": "custom",
                    }
                },
            },
        )
        stored = json.loads(serve.LOCAL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(stored["ai"]["providers"]["local"]["api_key"], "super-secret")
        self.assertNotIn("super-secret", json.dumps(again))

    def test_test_and_run_and_save_note(self):
        self._json(
            "/api/ai",
            {
                "default_provider": "local",
                "providers": {
                    "local": {
                        "label": "Dummy",
                        "base_url": self.fake_base,
                        "api_key": "k",
                        "models": ["dummy-1"],
                    }
                },
            },
        )
        ping, status = self._json("/api/ai/test", {"provider": "local"})
        self.assertEqual(status, 200)
        self.assertTrue(ping["ok"])
        self.assertIn("pong", ping["text"])
        models, _ = self._json("/api/ai/models", {"provider": "local"})
        self.assertIn("dummy-1", models["models"])
        run, _ = self._json("/api/ai/run", {"provider": "local", "path": "hello.md", "preset": "summarize"})
        self.assertTrue(run["ok"])
        saved, _ = self._json(
            "/api/ai/save",
            {"path": "hello.ai.md", "text": "# Out\n", "overwrite": False},
        )
        self.assertTrue(saved["ok"])
        self.assertTrue((self.notes / "hello.ai.md").is_file())
        from urllib.error import HTTPError

        with self.assertRaises(HTTPError) as ctx:
            self._json("/api/ai/save", {"path": "hello.ai.md", "text": "x", "overwrite": False})
        self.assertEqual(ctx.exception.code, 409)

    def test_config_save_gutter(self):
        data, status = self._json("/api/config", {"gutter": "2rem"})
        self.assertEqual(status, 200)
        self.assertEqual(data["config"]["gutter"], "2rem")
        disk = json.loads(serve.CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(disk["gutter"], "2rem")
        self.assertNotIn("ai", disk)

    def test_memory_visit_and_enrich(self):
        data, status = self._json("/api/memory/visit", {"path": "hello.md"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertTrue(data["fresh"])
        self.assertTrue((self.notes / serve.MEMORY_NAME).is_file())
        packed, _ = self._json("/api/ai", {
            "default_provider": "local",
            "providers": {
                "local": {
                    "label": "Dummy",
                    "base_url": self.fake_base,
                    "api_key": "k",
                    "models": ["dummy-1"],
                }
            },
        })
        self.assertTrue(packed["ok"])
        rich, status = self._json("/api/memory/enrich", {"path": "hello.md"})
        self.assertEqual(status, 200)
        self.assertTrue(rich.get("enriched"))
        self.assertEqual(rich["doc"]["next_action"], "Open the other note")
        self.assertEqual(len(rich["doc"]["tldr"]), 3)
        again, _ = self._json("/api/memory/enrich", {"path": "hello.md"})
        self.assertFalse(again.get("enriched"))

    def _save_dummy(self):
        self._json(
            "/api/ai",
            {
                "default_provider": "local",
                "providers": {
                    "local": {
                        "label": "Dummy",
                        "base_url": self.fake_base,
                        "api_key": "k",
                        "models": ["dummy-1"],
                    }
                },
            },
        )

    def test_chat_jsonl_sends_note_once_then_history(self):
        self._save_dummy()
        token = "UNIQUE_TOKEN_XYZ"
        (self.notes / "chatnote.md").write_text(
            "# Chat note\n\n%s only in the body.\n" % token, encoding="utf-8"
        )
        self.fake_payloads.clear()
        first, status = self._json(
            "/api/chat",
            {"path": "chatnote.md", "preset": "ask", "prompt": "What is this?"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(first["ok"])
        self.assertTrue(first["attached_note"])
        chat_file = self.notes / serve.CHAT_DIR / "chatnote.md.jsonl"
        self.assertTrue(chat_file.is_file())
        blob = json.dumps(self.fake_payloads[-1])
        self.assertIn(token, blob)
        self.assertIn("What is this?", blob)
        self.fake_payloads.clear()
        second, _ = self._json(
            "/api/chat",
            {"path": "chatnote.md", "preset": "ask", "prompt": "Say more"},
        )
        self.assertTrue(second["ok"])
        self.assertFalse(second["attached_note"])
        blob2 = json.dumps(self.fake_payloads[-1])
        self.assertNotIn(token, blob2)
        self.assertIn("What is this?", blob2)
        self.assertIn("Say more", blob2)
        roles = [m["role"] for m in second["messages"] if m["role"] in ("user", "assistant")]
        self.assertGreaterEqual(len(roles), 4)
        got, _ = self._json("/api/chat?path=chatnote.md")
        self.assertEqual(len(got["messages"]), len(second["messages"]))
        (self.notes / "chatnote.md").write_text(
            "# Chat note\n\nChanged %s body.\n" % token, encoding="utf-8"
        )
        listed, _ = self._json("/api/chat?path=chatnote.md")
        self.assertTrue(listed["note_changed"])
        self.assertGreaterEqual(len(listed["messages"]), 4)
        self.fake_payloads.clear()
        third, _ = self._json(
            "/api/chat",
            {"path": "chatnote.md", "preset": "ask", "prompt": "After edit"},
        )
        self.assertTrue(third["attached_note"])
        blob3 = json.dumps(self.fake_payloads[-1])
        self.assertIn(token, blob3)
        asst = [m for m in third["messages"] if m["role"] == "assistant"][-1]
        retried, _ = self._json("/api/chat/retry", {"path": "chatnote.md", "id": asst["id"]})
        self.assertTrue(retried["ok"])
        assts = [m for m in retried["messages"] if m["role"] == "assistant"]
        users = [m for m in retried["messages"] if m["role"] == "user"]
        self.assertEqual(users[-1]["text"], "After edit")
        self.assertTrue(all(m["id"] != asst["id"] for m in assts))
        first_user = [m for m in retried["messages"] if m["role"] == "user"][0]
        later_users = [m for m in retried["messages"] if m["role"] == "user"]
        self.assertGreaterEqual(len(later_users), 2)
        self.fake_payloads.clear()
        edited, status = self._json(
            "/api/chat/edit",
            {"path": "chatnote.md", "id": first_user["id"], "prompt": "Edited question"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(edited["ok"])
        users2 = [m for m in edited["messages"] if m["role"] == "user"]
        self.assertEqual(len(users2), 1)
        self.assertEqual(users2[0]["id"], first_user["id"])
        self.assertEqual(users2[0]["text"], "Edited question")
        blob4 = json.dumps(self.fake_payloads[-1])
        self.assertIn("Edited question", blob4)
        self.assertNotIn("After edit", blob4)
        from urllib.error import HTTPError

        with self.assertRaises(HTTPError) as ctx:
            self._json(
                "/api/chat/edit",
                {"path": "chatnote.md", "id": edited["id"], "prompt": "nope"},
            )
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
