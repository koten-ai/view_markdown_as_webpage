# Tests

All tests live in this folder. Keywords use YAKE from the repo-root
`requirements.txt`. Playwright needs the extra packages below.

## Python

From the repo root (venv with YAKE):

```bash
.venv/bin/python -m unittest discover -s tests
```

Covers `VERSION`, note listing, default-doc, path safety, last-folder reopen,
the HTTP JSON API (`/api/state`, `/api/notes`), config save, AI helpers
(key redact / keep, dummy Chat Completions run), the on-disk provider /
prompt catalogs (`ai/providers.json`, `ai/prompts/*.json`), and folder
memory (`_memory.json` keyword counts, hash skip, enrich pack), and
Ask chat (`_chats/<note>.jsonl`, note attached once per hash, retry).

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
