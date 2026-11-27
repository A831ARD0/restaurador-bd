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
RUTA_ZIP="$TMPDIR/app-para-notarizar.zip"
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

# Apple recomienda notarizar y GRAPAR la app antes de meterla en el DMG: asi el
# ticket viaja dentro de la app y Gatekeeper la acepta aunque no haya internet.
echo "Notarizando la app (tarda unos minutos)..."
rm -f "$RUTA_ZIP"
ditto -c -k --keepParent "$APP" "$RUTA_ZIP"
xcrun notarytool submit "$RUTA_ZIP" --keychain-profile "$PERFIL" --wait
xcrun stapler staple "$APP"
rm -f "$RUTA_ZIP"

echo "Armando el DMG con la app ya grapada..."
rm -rf dist/dmg "$DMG"
mkdir -p dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications "dist/dmg/Aplicaciones"
hdiutil create -volname "Restaurador de BD" -srcfolder dist/dmg -ov -format UDZO "$DMG" >/dev/null
rm -rf dist/dmg
codesign --force --timestamp --sign "$IDENTIDAD" "$DMG"

echo "Notarizando el DMG..."
xcrun notarytool submit "$DMG" --keychain-profile "$PERFIL" --wait
xcrun stapler staple "$DMG"

echo
echo "Comprobacion final:"
xcrun stapler validate "$APP"
spctl -a -vvv -t install "$DMG" 2>&1 | head -3
echo "Listo: la app y el DMG llevan el ticket grapado."
