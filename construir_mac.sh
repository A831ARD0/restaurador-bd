#!/bin/bash
# Genera "Restaurador de BD.app" y el instalador .dmg (solo se corre en Mac).
set -e
cd "$(dirname "$0")"
# Preferir un Python moderno: el que trae macOS es 3.9 y da problemas al empaquetar
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
[ -d .venv ] || "$PY" -m venv .venv
echo "Compilando con $("./.venv/bin/python" -V)"
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
cat > "dist/dmg/LEEME - si macOS no la deja abrir.txt" <<'TXT'
Si al abrir la app macOS dice que "Apple no pudo verificar que no contenga
software malicioso", NO le des a "Mover al basurero": pulsa "Listo" y haz
cualquiera de estas dos cosas, una sola vez.

A) Ajustes del Sistema -> Privacidad y seguridad -> baja hasta "Seguridad"
   -> junto a "Restaurador de BD" pulsa "Abrir de todos modos".

B) En la Terminal:
   xattr -dr com.apple.quarantine "/Applications/Restaurador de BD.app"

Es el aviso normal de macOS para apps repartidas fuera de la App Store sin
una cuenta de desarrollador de Apple (99 USD/ano). El codigo esta completo
y a la vista en: https://github.com/A831ARD0/restaurador-bd
TXT
hdiutil create -volname "Restaurador de BD" -srcfolder dist/dmg -ov -format UDZO \
  "dist/Restaurador de BD.dmg" >/dev/null
rm -rf dist/dmg
echo
echo "Listo:"
echo "  dist/Restaurador de BD.app   (la aplicacion)"
echo "  dist/Restaurador de BD.dmg   (el instalador para repartir)"
