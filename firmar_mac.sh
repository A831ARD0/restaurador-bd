#!/bin/bash
# Firma y notariza la app de macOS para que Gatekeeper no la bloquee.
#
# Requisitos (una sola vez):
#   1. Un certificado "Developer ID Application" en el llavero.
#      Xcode -> Settings -> Accounts -> Manage Certificates -> + -> Developer ID Application
#   2. Guardar las credenciales de notarizacion en el llavero:
#      xcrun notarytool store-credentials "notarytool" \
#        --apple-id TU_APPLE_ID --team-id TU_TEAM_ID --password CONTRASENA_DE_APP
#      (la contrasena de app se crea en https://appleid.apple.com -> Seguridad)
#
# Uso:  ./firmar_mac.sh            (despues de ./construir_mac.sh)
set -e
cd "$(dirname "$0")"

APP="dist/Restaurador de BD.app"
DMG="dist/Restaurador de BD.dmg"
PERFIL="${PERFIL_NOTARIZACION:-notarytool}"

IDENTIDAD=$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 |
            sed -E 's/.*"(.*)"/\1/')
if [ -z "$IDENTIDAD" ]; then
  echo "No encontre ningun certificado \"Developer ID Application\" en el llavero."
  echo "Creálo en Xcode -> Settings -> Accounts -> Manage Certificates -> + -> Developer ID Application"
  exit 1
fi
echo "Firmando con: $IDENTIDAD"

# El runtime endurecido es obligatorio para notarizar
codesign --force --deep --timestamp --options runtime \
         --sign "$IDENTIDAD" "$APP"
codesign --verify --strict --verbose=2 "$APP"

echo "Rehaciendo el DMG con la app ya firmada..."
rm -rf dist/dmg "$DMG"
mkdir -p dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications "dist/dmg/Aplicaciones"
hdiutil create -volname "Restaurador de BD" -srcfolder dist/dmg -ov -format UDZO "$DMG" >/dev/null
rm -rf dist/dmg
codesign --force --timestamp --sign "$IDENTIDAD" "$DMG"

if ! xcrun notarytool history --keychain-profile "$PERFIL" >/dev/null 2>&1; then
  echo
  echo "La app y el DMG ya estan firmados, pero falta notarizar."
  echo "Guarda las credenciales una sola vez y vuelve a correr este script:"
  echo
  echo "  xcrun notarytool store-credentials \"$PERFIL\" \\"
  echo "    --apple-id TU_APPLE_ID --team-id \$(echo \"$IDENTIDAD\" | sed -E 's/.*\((.*)\)/\1/')"
  echo
  echo "(la contrasena es una app-specific password de appleid.apple.com -> Seguridad)"
  exit 2
fi

echo "Enviando a notarizar (tarda unos minutos)..."
xcrun notarytool submit "$DMG" --keychain-profile "$PERFIL" --wait

echo "Grapando el resultado..."
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"

echo
echo "Listo. Comprobacion final:"
spctl -a -vvv -t install "$DMG" || true
echo "Ya se puede subir al release; se abrira con doble clic sin avisos."
