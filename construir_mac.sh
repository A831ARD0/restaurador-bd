#!/bin/bash
# Genera "Restaurador de BD.app" y el instalador .dmg (solo se corre en Mac).
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet pymysql pywebview pyinstaller
./.venv/bin/pyinstaller --noconfirm --clean --windowed \
  --name "Restaurador de BD" \
  --osx-bundle-identifier io.github.a831ard0.restauradorbd \
  --icon recursos/icono.icns \
  --collect-all webview \
  --hidden-import pymysql \
  restaurador_bd.py
rm -rf dist/dmg "dist/Restaurador de BD.dmg"
mkdir -p dist/dmg
cp -R "dist/Restaurador de BD.app" dist/dmg/
ln -s /Applications "dist/dmg/Aplicaciones"
hdiutil create -volname "Restaurador de BD" -srcfolder dist/dmg -ov -format UDZO \
  "dist/Restaurador de BD.dmg" >/dev/null
rm -rf dist/dmg
echo
echo "Listo:"
echo "  dist/Restaurador de BD.app   (la aplicacion)"
echo "  dist/Restaurador de BD.dmg   (el instalador para repartir)"
