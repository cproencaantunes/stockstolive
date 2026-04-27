#!/bin/bash
# start.sh — Ponto de entrada no Railway
# Arranca o dashboard Flask + o agente em paralelo

set -e

echo "━━ TRADING AGENT — ARRANQUE ━━━━━━━━━━━━━━━━"
echo "Provider: $LLM_PROVIDER"
echo "Modelo:   $LLM_MODEL"
echo "IBKR:     $IBKR_TRADING_MODE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

mkdir -p data logs

# Configurar git para sincronização de estado
git config user.email "agent@trading.local" 2>/dev/null || true
git config user.name  "Trading Agent"       2>/dev/null || true

# Arrancar dashboard Flask em background
echo "A iniciar dashboard..."
PORT=${PORT:-8080} python dashboard/app.py &
DASHBOARD_PID=$!

# Aguardar dashboard estar pronto
sleep 3

# Arrancar agente principal
echo "A iniciar agente..."
python stockstolive.py &
AGENT_PID=$!

echo "Dashboard PID: $DASHBOARD_PID"
echo "Agente PID:    $AGENT_PID"

# Manter processo vivo
wait $AGENT_PID
