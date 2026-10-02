# Desktop builds

Double-click installers so people do not need a terminal or a Python venv.
Shipped files are on
[GitHub Releases](https://github.com/koten-ai/view_markdown_as_webpage/releases).

| OS | Artifact |
| --- | --- |
| macOS | `dist/Markdown-Viewer-<version>-macos-<arch>.dmg` — drag **Markdown Viewer** to Applications |
| Windows | `dist/Markdown-Viewer-<version>-windows-x64.exe` — one-file app |

The first launch opens a browser at `http://127.0.0.1:8765` and a small **Open / Quit** window. Recents and API keys live in:

- macOS: `~/Library/Application Support/Markdown Viewer/`
- Windows: `%APPDATA%\Markdown Viewer\`

The app is unsigned. On a Mac, right-click the app → Open the first time. On Windows, choose **More info** → **Run anyway** if SmartScreen warns.

## Build

macOS (this machine):

```bash
bash packaging/build_macos.sh
```

Windows (PowerShell, Python 3.11):

```powershell
./packaging/build_windows.ps1
```

GitHub Actions workflow `.github/workflows/desktop.yml` builds both on `v*` tags or **Run workflow**.

Icons are regenerated with `packaging/.venv/bin/python packaging/make_icons.py` (navy square, cyan inner tile, **Md**).
