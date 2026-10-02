#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3.11}"
VENV="$ROOT/packaging/.venv"
VERSION="$("$PY" -c "import pathlib,re; t=pathlib.Path('serve.py').read_text(); print(re.search(r'VERSION = \"([^\"]+)\"', t).group(1))")"
ARCH="$(uname -m)"

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" install -U pip
"$VENV/bin/pip" install -r packaging/requirements.txt
"$VENV/bin/python" packaging/make_icons.py
"$VENV/bin/pyinstaller" --noconfirm --clean packaging/markdown-viewer.spec

APP="$ROOT/dist/Markdown Viewer.app"
if [[ ! -d "$APP" ]]; then
  echo "PyInstaller did not write $APP" >&2
  exit 1
fi
STAGE="$ROOT/dist/dmg-root"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="$ROOT/dist/Markdown-Viewer-${VERSION}-macos-${ARCH}.dmg"
rm -f "$DMG"
hdiutil create -volname "Markdown Viewer" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "dmg  $DMG"
echo "app  $APP"
