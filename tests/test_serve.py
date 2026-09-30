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
from http.server import ThreadingHTTPServer
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


if __name__ == "__main__":
    unittest.main()
