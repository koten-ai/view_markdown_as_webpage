# Tests

All tests live in this folder. The viewer itself stays stdlib-only; only the
Playwright suite needs extra packages.

## Python (no pip)

From the repo root:

```bash
python3 -m unittest discover -s tests
```

Covers `VERSION`, note listing, default-doc, path safety, last-folder reopen,
and the HTTP JSON API (`/api/state`, `/api/notes`).

## Playwright

Homebrew Python is PEP 668, so use a venv (gitignored):

```bash
python3 -m venv tests/.venv
tests/.venv/bin/pip install -r tests/requirements.txt
tests/.venv/bin/playwright install chromium
tests/.venv/bin/python -m unittest tests.test_viewer
```

These start `serve.py` against `tests/fixtures/notes`, so they do not touch
your real `config.local.json` (`MDVIEW_LOCAL` points at a temp file).

If Playwright is not installed, `test_viewer.py` is skipped.
