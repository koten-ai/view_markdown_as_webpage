#!/usr/bin/env python3
"""Playwright tests for the reader UI.

Skipped when the playwright package is not installed:

    python3 -m pip install -r tests/requirements.txt
    python3 -m playwright install chromium
    python3 -m unittest tests.test_viewer
"""
from __future__ import annotations

import json
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
        page.add_init_script("try { localStorage.removeItem('mdview-ai'); } catch (e) {}")
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
        box.fill("two")
        expect(page.locator('.nav-group[data-group="atlas"]')).to_be_hidden()
        expect(page.locator('a[data-path="blogs/two.md"]')).to_be_visible()
        expect(page.locator('a[data-path="blogs/three.md"]')).to_be_hidden()
        expect(page.locator('a[data-path="README.md"]')).to_be_hidden()
        mark = page.locator("#nav mark").first
        expect(mark).to_be_visible()
        color = mark.evaluate("el => getComputedStyle(el).color")
        bg = mark.evaluate("el => getComputedStyle(el).backgroundColor")
        self.assertNotEqual(color, bg)
        box.fill("")
        expect(page.locator('.nav-group[data-group="atlas"]')).to_be_visible()
        expect(page.locator('a[data-path="blogs/three.md"]')).to_be_visible()

    def test_rail_edge_is_draggable(self):
        page = self._open_reader()
        page.evaluate("() => localStorage.removeItem('mdview-rail-w')")
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(".nav-folder").first).to_be_visible()
        handle = page.locator("#rail-resize")
        expect(handle).to_be_visible()
        rail = page.locator("#nav")
        before = rail.bounding_box()["width"]
        box = handle.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 80)
        page.mouse.down()
        page.mouse.move(box["x"] + 140, box["y"] + 80, steps=8)
        page.mouse.up()
        after = rail.bounding_box()["width"]
        self.assertGreaterEqual(after, before + 80)
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(".nav-folder").first).to_be_visible()
        again = page.locator("#nav").bounding_box()["width"]
        self.assertAlmostEqual(again, after, delta=4)
        page.set_viewport_size({"width": 390, "height": 800})
        expect(page.locator("#rail-resize")).to_be_hidden()

    def test_settings_gear_opens_tabs(self):
        page = self._open_reader()
        gear = page.locator("#settings-open")
        ver = page.locator("#app-version")
        expect(gear).to_be_visible()
        expect(ver).to_be_visible()
        gbox = gear.bounding_box()
        vbox = ver.bounding_box()
        self.assertIsNotNone(gbox)
        self.assertIsNotNone(vbox)
        self.assertLess(gbox["x"], vbox["x"])
        self.assertGreaterEqual(gbox["width"], 30)
        self.assertGreaterEqual(gbox["height"], 30)
        gear.click()
        dialog = page.locator("#settings")
        expect(dialog).to_be_visible()
        expect(page.locator("#pane-viewer")).to_be_visible()
        page.locator("#tab-ai").click()
        expect(page.locator("#pane-ai")).to_be_visible()
        expect(page.locator("#ai-base")).to_be_visible()
        catalog = page.locator("#ai-catalog")
        expect(catalog).to_contain_text("xAI (Grok)")
        expect(catalog).to_contain_text("OpenAI")
        expect(catalog).to_contain_text("Anthropic")
        expect(catalog).to_contain_text("Google Gemini")
        expect(catalog).to_contain_text("Ollama (local)")
        expect(catalog).to_contain_text("OpenRouter")
        expect(catalog).to_contain_text("Custom")
        page.locator("#tab-run").click()
        expect(page.locator("#pane-run")).to_be_visible()
        expect(page.locator("#run-go")).to_be_visible()
        expect(page.locator("#run-go")).to_be_disabled()
        presets = page.locator("#run-preset")
        expect(presets).to_contain_text("Summarize")
        expect(presets).to_contain_text("Ask")
        expect(presets).to_contain_text("Proofread")
        page.locator("#settings-close").click()
        expect(dialog).to_be_hidden()

    def test_ai_toggle_left_of_folders(self):
        page = self._open_reader()
        toggle = page.locator("#ai-toggle")
        folders = page.locator(".folders-link")
        expect(toggle).to_be_visible()
        expect(folders).to_be_visible()
        tbox = toggle.bounding_box()
        fbox = folders.bounding_box()
        self.assertIsNotNone(tbox)
        self.assertIsNotNone(fbox)
        self.assertLess(tbox["x"], fbox["x"])
        expect(toggle).to_have_attribute("aria-pressed", "false")
        fill = page.locator("#ai-toggle").evaluate("el => getComputedStyle(el).backgroundColor")
        self.assertIn(fill.replace(" ", ""), ("rgba(0,0,0,0)", "transparent", "rgba(0,0,0,0.0)"))
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "true")
        page.reload(wait_until="domcontentloaded")
        expect(page.locator(".nav-folder").first).to_be_visible()
        expect(page.locator("#ai-toggle")).to_have_attribute("aria-pressed", "true")
        on_fill = page.locator("#ai-toggle").evaluate("el => getComputedStyle(el).backgroundColor")
        self.assertNotIn(on_fill.replace(" ", ""), ("rgba(0,0,0,0)", "transparent"))
        page.locator("#ai-toggle").click()
        expect(page.locator("#ai-toggle")).to_have_attribute("aria-pressed", "false")
        page.set_viewport_size({"width": 390, "height": 800})
        crumb = page.locator("#crumb")
        expect(crumb).to_be_visible()
        cbox = crumb.bounding_box()
        abox = page.locator("#ai-toggle").bounding_box()
        self.assertIsNotNone(cbox)
        self.assertIsNotNone(abox)
        self.assertGreater(cbox["y"], abox["y"] + 8)

    def test_memory_keywords_show_on_open(self):
        page = self._open_reader()
        keys = page.locator("#memory-keys")
        expect(keys).to_be_visible()
        expect(keys).to_contain_text("Keywords")
        expect(page.locator("#memory-cards")).to_be_hidden()
        expect(page.locator("#memory-actions")).to_be_hidden()
        page.locator("#ai-toggle").click()
        expect(page.locator("#memory-cards")).to_be_visible()
        expect(page.locator("#memory-cards")).to_contain_text("TL;DR")
        headings = page.locator("#memory-cards h3")
        expect(headings).to_have_count(3)
        expect(headings.nth(0)).to_have_text("TL;DR")
        expect(headings.nth(1)).to_have_text("Important idea")
        expect(headings.nth(2)).to_have_text("Next action")
        colors = page.evaluate(
            """() => {
              const mem = getComputedStyle(document.getElementById("memory"));
              const doc = getComputedStyle(document.getElementById("doc"));
              return { memory: mem.backgroundColor, doc: doc.backgroundColor };
            }"""
        )
        self.assertNotEqual(colors["memory"], colors["doc"])
        expect(page.locator("#memory-actions")).to_be_visible()
        expect(page.locator("#memory-actions")).to_contain_text("Summarize")
        expect(page.locator("#memory-actions")).not_to_contain_text("Memory pack")
        action = page.locator("#memory-actions .memory-action").first
        expect(action).to_be_visible()
        expect(page.locator("#memory-actions .memory-chip")).to_have_count(0)
        action_look = action.evaluate(
            """el => {
              const s = getComputedStyle(el);
              return { bg: s.backgroundColor, radius: s.borderRadius, color: s.color };
            }"""
        )
        expect(page.locator("#memory-ask-toggle")).to_be_visible()
        ask_pos = page.evaluate(
            """() => {
              const btn = document.getElementById("memory-ask-toggle").getBoundingClientRect();
              const bar = document.querySelector(".memory-ask-bar").getBoundingClientRect();
              return { btnRight: btn.right, barRight: bar.right, btnLeft: btn.left, barLeft: bar.left };
            }"""
        )
        self.assertLess(ask_pos["barRight"] - ask_pos["btnRight"], 4)
        self.assertGreater(ask_pos["btnLeft"] - ask_pos["barLeft"], (ask_pos["barRight"] - ask_pos["barLeft"]) * 0.5)
        label_color = page.locator("#memory-keys .memory-label").evaluate(
            "el => getComputedStyle(el).color"
        )
        self.assertNotEqual(label_color.replace(" ", ""), "rgb(123,136,152)")
        chip = page.locator("#memory-keys .memory-chip").first
        chip_bg = chip.evaluate("el => getComputedStyle(el).backgroundColor")
        self.assertNotIn("230", chip_bg)
        chip_look = chip.evaluate(
            """el => {
              const s = getComputedStyle(el);
              return { bg: s.backgroundColor, radius: s.borderRadius, color: s.color };
            }"""
        )
        self.assertNotEqual(action_look["bg"], chip_look["bg"])
        self.assertNotEqual(action_look["radius"], chip_look["radius"])
        self.assertNotEqual(action_look["color"], chip_look["color"])
        expect(chip).to_have_attribute("aria-pressed", "false")
        chip.click()
        expect(chip).to_have_attribute("aria-pressed", "true")
        on_bg = chip.evaluate("el => getComputedStyle(el).backgroundColor")
        self.assertNotEqual(on_bg, chip_bg)
        kw_var = chip.evaluate("el => getComputedStyle(el).getPropertyValue('--kw').trim().toLowerCase()")
        self.assertIn(
            kw_var,
            {
                "#f08a2a",
                "#f0b429",
                "#e2d04a",
                "#9fd36a",
                "#5cbc7a",
                "#3dbe9a",
                "#4ec4e0",
                "#6bb3f0",
                "#8b9aef",
                "#b48ae8",
                "#e07ac8",
                "#e889b4",
                "#e87a6b",
                "#ef9a9a",
            },
        )
        hit = page.locator("#doc mark.kw-hit").first
        expect(hit).to_be_visible()
        hit_bg = hit.evaluate("el => getComputedStyle(el).backgroundColor")
        self.assertEqual(hit_bg, on_bg)
        hit_var = hit.evaluate("el => getComputedStyle(el).getPropertyValue('--kw').trim().toLowerCase()")
        self.assertEqual(hit_var, kw_var)
        chip.click()
        expect(chip).to_have_attribute("aria-pressed", "false")
        expect(page.locator("#doc mark.kw-hit")).to_have_count(0)
        page.locator("#memory-ask-toggle").click()
        expect(page.locator("#memory-chat-log")).to_be_visible()
        expect(page.locator("#memory-ask-input")).to_be_visible()
        expect(page.locator("#memory-ask-toggle")).to_have_text("Close")
        go_pos = page.evaluate(
            """() => {
              const btn = document.getElementById("memory-ask-go").getBoundingClientRect();
              const box = document.querySelector(".chat-compose").getBoundingClientRect();
              return { btnRight: btn.right, boxRight: box.right };
            }"""
        )
        self.assertLess(go_pos["boxRight"] - go_pos["btnRight"], 4)
        page.locator("#memory-ask-toggle").click()
        expect(page.locator("#memory-ask")).to_be_hidden()
        expect(page.locator("#memory-ask-toggle")).to_have_text("Ask…")
        page.locator("#ai-toggle").click()
        expect(page.locator("#memory-cards")).to_be_hidden()
        expect(page.locator("#memory-actions")).to_be_hidden()

    def test_memory_cards_wait_then_stream(self):
        page = self._open_reader()
        payload = {
            "ok": True,
            "enriched": True,
            "doc": {
                "path": "README.md",
                "title": "Fixture notes",
                "sha256": "test-stream",
                "tldr": ["Hello claim", "Status draft", "Not a 1.0 claim"],
                "next_action": "Open the other note",
                "important": "Keep the source file",
                "rich": True,
                "keywords": [["fixture notes", 3]],
                "related": [],
            },
        }

        def handle_enrich(route):
            time.sleep(0.4)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(payload),
            )

        page.route("**/api/memory/enrich", handle_enrich)
        page.locator("#ai-toggle").click()
        expect(page.locator("#memory-cards")).to_be_visible()
        expect(page.locator("#memory-cards .memory-wait")).to_have_count(3)
        expect(page.locator("#memory-cards")).to_have_attribute("aria-busy", "true")
        expect(page.locator("#memory-cards")).to_contain_text("Hello claim")
        expect(page.locator("#memory-cards")).to_contain_text("Keep the source file")
        expect(page.locator("#memory-cards")).to_contain_text("Open the other note")
        expect(page.locator("#memory-cards .memory-wait")).to_have_count(0)
        expect(page.locator("#memory-cards [data-card=tldr] li")).to_have_count(3)

    def test_memory_cards_cached_show_instantly(self):
        page = self._open_reader()
        payload = {
            "ok": True,
            "doc": {
                "path": "README.md",
                "title": "Fixture notes",
                "sha256": "cached-pack",
                "tldr": ["Hello claim", "Status draft", "Not a 1.0 claim"],
                "next_action": "Open the other note",
                "important": "Keep the source file",
                "rich": True,
                "keywords": [["fixture notes", 3]],
                "related": [],
            },
        }

        def handle_visit(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(payload),
            )

        page.route("**/api/memory/visit", handle_visit)
        page.locator("#ai-toggle").click()
        expect(page.locator("#memory-cards")).to_contain_text("Hello claim")
        expect(page.locator("#memory-cards")).to_contain_text("Keep the source file")
        expect(page.locator("#memory-cards .memory-wait")).to_have_count(0)
        expect(page.locator("#memory-cards .memory-caret")).to_have_count(0)
        expect(page.locator("#memory-cards [data-card=tldr]")).to_have_count(0)
        expect(page.locator("#memory-cards li")).to_have_count(3)

    def test_selection_menu_copy_and_insights(self):
        page = self._open_reader()
        expect(page.locator("#doc")).to_be_visible()
        selected = page.locator("#doc").evaluate(
            """el => {
              const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
              let node;
              while ((node = walker.nextNode())) {
                const raw = node.textContent || "";
                if (raw.trim().length < 12) continue;
                const range = document.createRange();
                range.selectNodeContents(node);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
                return sel.toString().trim();
              }
              return "";
            }"""
        )
        self.assertTrue(selected)
        menu = page.locator("#sel-menu")
        expect(menu).to_be_visible()
        expect(menu).to_contain_text("Copy")
        expect(menu).to_contain_text("AI Insights")
        page.locator("#sel-insight").click()
        expect(page.locator("#sel-insight-box")).to_be_visible()
        expect(page.locator("#sel-quote")).to_contain_text(selected[:12])
        expect(page.locator("#sel-input")).to_be_visible()
        expect(page.locator("#sel-input")).to_have_attribute("placeholder", "Ask about this passage")
        expect(page.locator("[data-insight=explain]")).to_have_text("Explain more")
        expect(page.locator("[data-insight=simplify]")).to_have_text("Simplify")
        expect(page.locator("#sel-hint")).to_be_visible()
        page.locator("#ai-toggle").click()
        expect(page.locator("#sel-hint")).to_be_hidden()
        page.locator("#sel-input").fill("What does this mean?")
        page.keyboard.press("Escape")
        expect(page.locator("#sel-menu")).to_be_hidden()
        page.locator("#ai-toggle").click()
        expect(page.locator("#ai-toggle")).to_have_attribute("aria-pressed", "false")

    def test_ask_user_bubble_has_edit_pencil(self):
        chat_dir = FIXTURES / "_chats"
        chat_dir.mkdir(exist_ok=True)
        chat_file = chat_dir / "README.md.jsonl"
        rows = [
            {
                "id": "s1",
                "ts": "2026-01-01T00:00:00Z",
                "role": "system",
                "kind": "note_snapshot",
                "text": "Using the current note.",
                "ok": True,
            },
            {
                "id": "u1",
                "ts": "2026-01-01T00:00:01Z",
                "role": "user",
                "kind": "chat",
                "text": "What is this fixture?",
                "ok": True,
            },
            {
                "id": "a1",
                "ts": "2026-01-01T00:00:02Z",
                "role": "assistant",
                "kind": "chat",
                "text": "A test note.",
                "ok": True,
            },
        ]
        chat_file.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        self.addCleanup(lambda: chat_file.exists() and chat_file.unlink())
        page = self._open_reader()
        page.locator("#ai-toggle").click()
        expect(page.locator("#memory-ask")).to_be_visible()
        expect(page.locator("#memory-ask-toggle")).to_have_text("Close")
        pencil = page.locator(".chat-user .chat-edit")
        expect(pencil).to_be_visible()
        boxes = page.evaluate(
            """() => {
              const p = document.querySelector(".chat-user .chat-edit").getBoundingClientRect();
              const b = document.querySelector(".chat-user .chat-bubble").getBoundingClientRect();
              return { px: p.x, bx: b.x };
            }"""
        )
        self.assertLess(boxes["px"], boxes["bx"])
        retry = page.locator(".chat-ai [data-retry]")
        copy_one = page.locator(".chat-ai [data-copy-one]")
        expect(retry).to_be_visible()
        expect(copy_one).to_be_visible()
        expect(retry).to_have_attribute("aria-label", "Retry")
        expect(copy_one).to_have_attribute("aria-label", "Copy")
        expect(retry.locator("svg")).to_be_visible()
        expect(retry.locator("svg path")).to_have_count(2)
        expect(retry.locator("svg polygon")).to_have_count(0)
        expect(copy_one.locator("svg")).to_be_visible()
        expect(retry).not_to_contain_text("Retry")
        expect(copy_one).not_to_contain_text("Copy")
        pencil.click()
        editor = page.locator(".chat-edit-input")
        wrap = page.locator(".chat-edit-wrap")
        expect(editor).to_be_visible()
        expect(wrap).to_be_visible()
        expect(editor).to_have_value("What is this fixture?")
        styles = editor.evaluate(
            """el => {
              const s = getComputedStyle(el);
              const wrap = el.closest(".chat-edit-wrap");
              const w = getComputedStyle(wrap);
              const log = document.getElementById("memory-chat-log");
              return {
                color: s.color,
                wrapBg: w.backgroundColor,
                width: wrap.getBoundingClientRect().width,
                log: log.getBoundingClientRect().width,
              };
            }"""
        )
        rgb = [int(x) for x in styles["color"].replace("rgb(", "").replace(")", "").split(",")]
        self.assertLess(sum(rgb) / 3, 80)
        wrap_rgb = [int(x) for x in styles["wrapBg"].replace("rgb(", "").replace("rgba(", "").replace(")", "").split(",")[:3]]
        self.assertGreater(sum(wrap_rgb) / 3, 200)
        self.assertGreater(styles["width"], styles["log"] * 0.7)
        editor.fill("What is this fixture, really?")
        page.keyboard.press("Escape")
        expect(page.locator(".chat-edit-input")).to_have_count(0)
        expect(page.locator(".chat-user .chat-md")).to_contain_text("What is this fixture?")
        page.locator("#memory-ask-toggle").click()
        expect(page.locator("#memory-ask")).to_be_hidden()
        expect(page.locator("#memory-ask-toggle")).to_have_text("Ask…")
        page.locator("#ai-toggle").click()
        expect(page.locator("#ai-toggle")).to_have_attribute("aria-pressed", "false")

    def test_table_first_body_row_sits_below_header(self):
        page = self._open_reader()
        page.goto(self.base + "/viewer.html?doc=table.md", wait_until="domcontentloaded")
        table = page.locator("#doc table").first
        expect(table).to_be_visible()
        expect(table).to_contain_text("Sales / RevOps")
        expect(table.locator("tbody tr")).to_have_count(3)
        geom = table.evaluate(
            """el => {
              const th = el.querySelector("thead th, th");
              const row = el.querySelector("tbody tr");
              const thR = th.getBoundingClientRect();
              const rowR = row.getBoundingClientRect();
              const thStyle = getComputedStyle(th);
              return {
                overlap: thR.bottom - rowR.top,
                firstCell: (row.cells[0].textContent || "").trim(),
                thTopCss: thStyle.top,
                thPosition: thStyle.position,
                wrapClass: el.parentElement && el.parentElement.className,
              };
            }"""
        )
        self.assertEqual(geom["wrapClass"], "table-wrap")
        self.assertEqual(geom["thPosition"], "sticky")
        self.assertEqual(geom["thTopCss"], "0px")
        self.assertEqual(geom["firstCell"], "Sales / RevOps")
        self.assertLessEqual(geom["overlap"], 1)
        stripe = table.evaluate(
            """el => {
              const rows = el.querySelectorAll("tbody tr");
              const odd = getComputedStyle(rows[0].cells[0]).backgroundColor;
              const even = getComputedStyle(rows[1].cells[0]).backgroundColor;
              return { odd, even, count: rows.length };
            }"""
        )
        self.assertNotEqual(stripe["odd"], stripe["even"])
        self.assertGreaterEqual(stripe["count"], 2)


@unittest.skipUnless(sync_playwright, "playwright not installed")
class SplashPickerTests(unittest.TestCase):
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

    def test_browse_lists_markdown_files_in_folder(self):
        page = self.page
        page.goto(self.base + "/", wait_until="domcontentloaded")
        expect(page.locator("#view-btn")).to_be_enabled()
        page.locator("#path-input").fill(str(FIXTURES))
        page.locator("#path-form button[type=submit]").click()
        expect(page.locator("#path-input")).to_have_value(str(FIXTURES))
        expect(page.locator(".dir-row.is-file", has_text="README.md")).to_be_visible()
        expect(page.locator(".dir-row.is-file", has_text="table.md")).to_be_visible()
        atlas = page.locator(".dir-row:not(.is-file)", has_text="atlas")
        expect(atlas).to_be_visible()
        expect(atlas).to_contain_text("md")
        colors = page.evaluate(
            """() => {
              const folder = document.querySelector(".dir-row:not(.is-file) strong");
              const file = document.querySelector(".dir-row.is-file strong");
              return {
                folder: folder ? getComputedStyle(folder).color : "",
                file: file ? getComputedStyle(file).color : "",
              };
            }"""
        )
        self.assertTrue(colors["folder"])
        self.assertTrue(colors["file"])
        self.assertNotEqual(colors["folder"], colors["file"])
        atlas.click()
        expect(page.locator(".dir-row.is-file", has_text="one.md")).to_be_visible()
        expect(page.locator("#md-count")).to_contain_text("markdown file")

