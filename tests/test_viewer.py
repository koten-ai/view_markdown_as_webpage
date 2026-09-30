#!/usr/bin/env python3
"""Playwright tests for the reader UI.

Skipped when the playwright package is not installed:

    python3 -m pip install -r tests/requirements.txt
    python3 -m playwright install chromium
    python3 -m unittest tests.test_viewer
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "notes"

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
    expect = None


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@unittest.skipUnless(sync_playwright, "playwright not installed")
class ViewerFoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = _free_port()
        cls.base = "http://127.0.0.1:%s" % cls.port
        env = os.environ.copy()
        env["MDVIEW_LOCAL"] = str(Path(cls.tmp.name) / "config.local.json")
        cls.proc = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "serve.py"),
                str(FIXTURES),
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 8
        last_err = None
        while time.time() < deadline:
            try:
                urllib.request.urlopen(cls.base + "/api/state", timeout=0.5).read()
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as err:
                last_err = err
                if cls.proc.poll() is not None:
                    raise RuntimeError("serve.py exited %s" % cls.proc.returncode) from err
                time.sleep(0.1)
        else:
            cls.proc.kill()
            raise RuntimeError("serve.py did not start: %s" % last_err)
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception:
            cls.browser = cls.pw.chromium.launch(channel="chrome")
        cls.context = cls.browser.new_context(viewport={"width": 1280, "height": 800})

    @classmethod
    def tearDownClass(cls):
        try:
            cls.context.close()
            cls.browser.close()
            cls.pw.stop()
        except Exception:
            pass
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
        cls.tmp.cleanup()

    def setUp(self):
        self.page = self.context.new_page()
        self.addCleanup(self.page.close)

    def _open_reader(self):
        page = self.page
        page.goto(self.base + "/viewer.html", wait_until="domcontentloaded")
        expect(page.locator(".nav-folder").first).to_be_visible()
        return page

    def test_version_from_state(self):
        page = self._open_reader()
        badge = page.locator("#app-version")
        expect(badge).to_be_visible()
        expect(badge).to_contain_text("v")

    def test_folder_names_are_distinct_and_have_fold_buttons(self):
        page = self._open_reader()
        folders = page.locator(".nav-folder")
        expect(folders).to_have_count(3)
        names = [t.strip() for t in folders.all_text_contents()]
        self.assertIn("notes", names)
        self.assertIn("atlas", names)
        self.assertIn("blogs", names)
        weight = page.locator(".nav-folder").nth(1).evaluate(
            "el => getComputedStyle(el).fontWeight"
        )
        self.assertGreaterEqual(int(weight), 600)
        expect(page.locator(".nav-fold")).to_have_count(3)

    def test_hide_show_one_folder(self):
        page = self._open_reader()
        atlas = page.locator('.nav-group[data-group="atlas"]')
        note = atlas.locator(".nav-group-body a")
        expect(note).to_be_visible()
        atlas.locator(".nav-fold").click()
        expect(atlas).to_have_class("nav-group is-collapsed")
        expect(note).to_be_hidden()
        expect(atlas.locator(".nav-fold")).to_have_attribute("aria-expanded", "false")
        atlas.locator(".nav-fold").click()
        expect(note).to_be_visible()
        expect(atlas.locator(".nav-fold")).to_have_attribute("aria-expanded", "true")

    def test_hide_all_and_show_all(self):
        page = self._open_reader()
        all_btn = page.locator("#nav-all")
        expect(all_btn).to_be_visible()
        expect(all_btn).to_have_text("Hide all")
        all_btn.click()
        expect(all_btn).to_have_text("Show all")
        expect(page.locator(".nav-group.is-collapsed")).to_have_count(3)
        expect(page.locator(".nav-group-body a").first).to_be_hidden()
        all_btn.click()
        expect(all_btn).to_have_text("Hide all")
        expect(page.locator(".nav-group.is-collapsed")).to_have_count(0)

    def test_sidebar_peek_sits_to_the_right(self):
        page = self._open_reader()
        rail = page.locator("#nav")
        link = page.locator('.nav-group[data-group="blogs"] .nav-group-body a').first
        expect(link).to_be_visible()
        rail_box = rail.bounding_box()
        link.hover()
        peek = page.locator("#peek")
        expect(peek).to_be_visible(timeout=4000)
        peek_box = peek.bounding_box()
        self.assertIsNotNone(rail_box)
        self.assertIsNotNone(peek_box)
        self.assertGreaterEqual(peek_box["x"], rail_box["x"] + rail_box["width"] - 2)

    def test_filter_highlights_fuzzy_matches(self):
        page = self._open_reader()
        box = page.locator("#nav-filter")
        box.fill("blog")
        expect(page.locator('.nav-group[data-group="atlas"]')).to_be_hidden()
        blogs = page.locator('.nav-group[data-group="blogs"]')
        expect(blogs).to_be_visible()
        expect(blogs.locator("mark").first).to_be_visible()
        expect(blogs.locator(".nav-group-body a")).to_have_count(2)
        box.fill("")
        expect(page.locator('.nav-group[data-group="atlas"]')).to_be_visible()


if __name__ == "__main__":
    unittest.main()
