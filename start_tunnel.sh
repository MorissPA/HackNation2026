#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=========================================================="
echo "🛡️  Risk Miner — Uruchamianie aplikacji i tunelu Cloudflare"
echo "=========================================================="

UVICORN_PID=""
cleanup() {
    echo ""
    echo "🛑 Zamykanie procesów..."
    if [ -n "$UVICORN_PID" ]; then
        kill "$UVICORN_PID" 2>/dev/null || true
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM

# 1. Sprawdź czy backend już działa
if curl -s http://127.0.0.1:8000/api/stats > /dev/null 2>&1; then
    echo "✅ Backend API już działa na porcie 8000."
else
    echo "🚀 Uruchamiam backend FastAPI (port 8000)..."
    .venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000 > /tmp/riskminer_api.log 2>&1 &
    UVICORN_PID=$!
    sleep 2
    if curl -s http://127.0.0.1:8000/api/stats > /dev/null 2>&1; then
        echo "✅ Backend API wystartował poprawnie (PID: $UVICORN_PID)."
    else
        echo "❌ Błąd startu backendu. Zobacz logi: cat /tmp/riskminer_api.log"
        exit 1
    fi
fi

# 2. Uruchom tunel Cloudflare
echo "🌐 Tworzę publiczny tunel HTTPS Cloudflare..."
echo "Skopiuj wygenerowany link HTTPS (np. https://xxx.trycloudflare.com):"
echo "----------------------------------------------------------"
.venv/bin/cloudflared tunnel --url http://127.0.0.1:8000
