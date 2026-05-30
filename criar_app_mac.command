#!/bin/bash
# Cria um bundle Nexum.app na sua pasta Aplicativos.
# O bundle usa o iniciar.command por baixo, mas aparece com ícone próprio
# na Spotlight, Dock e Launchpad.

set -e
cd "$(dirname "$0")"
PASTA_APP="$(pwd)"

NOME_APP="Nexum"
APP_DIR="$HOME/Applications/${NOME_APP}.app"

# Garante a pasta Applications do usuário
mkdir -p "$HOME/Applications"

# Remove app anterior
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# === Info.plist ===
cat > "$APP_DIR/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>           <string>${NOME_APP}</string>
    <key>CFBundleDisplayName</key>    <string>${NOME_APP}</string>
    <key>CFBundleExecutable</key>     <string>iniciar</string>
    <key>CFBundleIconFile</key>       <string>icon.icns</string>
    <key>CFBundleIdentifier</key>     <string>local.nexum.app</string>
    <key>CFBundlePackageType</key>    <string>APPL</string>
    <key>CFBundleVersion</key>        <string>1.2</string>
    <key>CFBundleShortVersionString</key> <string>1.2</string>
    <key>NSHighResolutionCapable</key> <true/>
    <key>LSUIElement</key>            <false/>
</dict>
</plist>
EOF

# === Script principal — chama o iniciar.command da pasta original ===
cat > "$APP_DIR/Contents/MacOS/iniciar" << EOF
#!/bin/bash
# Wrapper que chama o iniciar.command na pasta da instalação
"${PASTA_APP}/iniciar.command"
EOF
chmod +x "$APP_DIR/Contents/MacOS/iniciar"

# === Ícone (.icns) ===
# Converte PNG para .icns usando ferramentas do próprio macOS
ICONSET="/tmp/financeiro_icon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

PNG="${PASTA_APP}/app/static/icon-256.png"
if [ -f "$PNG" ]; then
    # iconutil precisa de tamanhos específicos
    sips -z 16 16     "$PNG" --out "$ICONSET/icon_16x16.png"     >/dev/null
    sips -z 32 32     "$PNG" --out "$ICONSET/icon_16x16@2x.png"  >/dev/null
    sips -z 32 32     "$PNG" --out "$ICONSET/icon_32x32.png"     >/dev/null
    sips -z 64 64     "$PNG" --out "$ICONSET/icon_32x32@2x.png"  >/dev/null
    sips -z 128 128   "$PNG" --out "$ICONSET/icon_128x128.png"   >/dev/null
    sips -z 256 256   "$PNG" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
    cp "$PNG"                "$ICONSET/icon_256x256.png"
    sips -z 512 512   "$PNG" --out "$ICONSET/icon_256x256@2x.png" >/dev/null 2>&1 || cp "$PNG" "$ICONSET/icon_256x256@2x.png"
    iconutil -c icns "$ICONSET" -o "$APP_DIR/Contents/Resources/icon.icns"
    rm -rf "$ICONSET"
    echo "✓ Ícone configurado"
else
    echo "[AVISO] Ícone não encontrado em $PNG"
fi

echo ""
echo "============================================"
echo " ✓ App criado em: $APP_DIR"
echo "============================================"
echo ""
echo "Próximos passos:"
echo "  1) Abra o Finder → Vá em 'Aplicativos' (Applications)"
echo "  2) Arraste 'Nexum' pro Dock se quiser"
echo "  3) Pra atualizar o app no futuro, basta substituir os arquivos"
echo "     desta pasta — o .app continua funcionando."
echo ""
echo "Pra abrir agora, dá 2 cliques em $APP_DIR ou usa o Spotlight."
echo ""
