#!/bin/bash
# Nexum — script de inicialização para Mac/Linux

cd "$(dirname "$0")"

echo ""
echo " ============================================"
echo "  NEXUM"
echo " ============================================"
echo ""

# === Verificar Python 3 ===
if ! command -v python3 &> /dev/null; then
    echo "[ERRO] Python 3 não encontrado."
    echo ""
    echo "No Mac, instale com:"
    echo "  1) Instale Homebrew: https://brew.sh"
    echo "  2) Rode: brew install python"
    read -p "Pressione ENTER para fechar..."
    exit 1
fi

# === Verificar pdftotext (Poppler) ===
if ! command -v pdftotext &> /dev/null; then
    echo "[AVISO] pdftotext não encontrado."
    echo "No Mac, instale com: brew install poppler"
    echo "(Sem isso, importação de PDFs não funciona.)"
    sleep 2
fi

# === Instalar dependências se faltarem ===
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "Instalando dependências pela primeira vez..."
    if pip3 install -r requirements.txt --break-system-packages 2>/dev/null; then
        echo "✓ Dependências instaladas."
    elif pip3 install -r requirements.txt 2>/dev/null; then
        echo "✓ Dependências instaladas."
    else
        echo "[ERRO] Falha ao instalar dependências."
        echo "Tente manualmente: pip3 install -r requirements.txt --break-system-packages"
        read -p "Pressione ENTER para fechar..."
        exit 1
    fi
fi

# === Achar Chrome ou alternativa ===
CHROME=""
if [ -d "/Applications/Google Chrome.app" ]; then
    CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
elif [ -d "/Applications/Microsoft Edge.app" ]; then
    CHROME="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
elif [ -d "/Applications/Brave Browser.app" ]; then
    CHROME="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
elif command -v google-chrome &> /dev/null; then
    CHROME="google-chrome"
elif command -v chromium &> /dev/null; then
    CHROME="chromium"
fi

# === Iniciar servidor em background ===
echo "Iniciando servidor..."
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8765 > /tmp/financeiro_server.log 2>&1 &
SERVER_PID=$!

# Garante que o servidor seja morto quando o script terminar
cleanup() {
    echo ""
    echo "Encerrando servidor (PID $SERVER_PID)..."
    kill $SERVER_PID 2>/dev/null
    exit 0
}
trap cleanup EXIT INT TERM

# === Esperar servidor responder (max 15s) ===
echo "Aguardando servidor subir..."
TENTATIVAS=0
while [ $TENTATIVAS -lt 30 ]; do
    if curl -s -o /dev/null http://127.0.0.1:8765/api/health 2>/dev/null; then
        break
    fi
    sleep 0.5
    TENTATIVAS=$((TENTATIVAS + 1))
done

if [ $TENTATIVAS -ge 30 ]; then
    echo "[ERRO] Servidor não respondeu em 15s."
    echo "Veja o log em /tmp/financeiro_server.log"
    cleanup
fi

# === Abrir Chrome em modo app ===
echo "Abrindo aplicativo..."
if [ -n "$CHROME" ]; then
    "$CHROME" --app=http://localhost:8765 --window-size=1400,900 &
    CHROME_PID=$!

    echo ""
    echo "App aberto."
    echo "Para encerrar tudo, feche esta janela ou pressione Ctrl+C"
    echo ""

    # Espera o Chrome fechar
    wait $CHROME_PID
    # Quando Chrome fecha, mata o servidor (cleanup roda automaticamente)
else
    echo "[AVISO] Chrome/Edge/Brave não encontrado, abrindo navegador padrão..."
    open "http://localhost:8765" 2>/dev/null || xdg-open "http://localhost:8765" 2>/dev/null

    echo ""
    echo "Para encerrar, pressione Ctrl+C ou feche esta janela."
    echo ""

    # Mantém vivo enquanto servidor roda
    wait $SERVER_PID
fi
