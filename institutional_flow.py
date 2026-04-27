"""
institutional_flow.py — Deteção de fluxo institucional.

Duas camadas:
1. Volume spike (gratuito — yfinance)
2. Unusual options activity (Unusual Whales API — $50/mês, opcional)

O agente deteta → alerta → tu decides se entras.
Nunca compra automaticamente.
"""

import logging, json, requests
from datetime import datetime, date
from pathlib import Path
import yfinance as yf
import numpy as np

from config import (
    UNUSUAL_WHALES_TOKEN,
    TIMEZONE,
)
from data import get_market_data
from llm_client import ask

log = logging.getLogger(__name__)

# ── WATCHLIST ─────────────────────────────────────────────────────
# Universo de ações a monitorizar (além do portfolio)
DEFAULT_WATCHLIST = [
    # Tech / AI
    "NVDA", "AMD", "MSFT", "GOOGL", "META", "AAPL", "AMZN",
    "ARM", "SMCI", "PLTR", "CRWV", "TSM", "AVGO",
    # Energia
    "XOM", "CVX", "OXY",
    # Financeiros
    "JPM", "GS", "BAC",
    # Biotech
    "LLY", "MRNA", "ABBV",
    # Momentum
    "TSLA", "COIN", "MSTR", "HOOD",
]

# ── THRESHOLDS ────────────────────────────────────────────────────
VOLUME_SPIKE_THRESHOLD    = 4.0    # 4x acima da média = sinal
VOLUME_EXTREME_THRESHOLD  = 7.0    # 7x = sinal forte
PRICE_MOVE_THRESHOLD      = 1.5    # 1.5% de movimento mínimo
UOA_MIN_PREMIUM           = 500_000  # $500k mínimo para UOA relevante
UOA_LARGE_PREMIUM         = 1_000_000  # $1M = alerta urgente


# ── CAMADA 1: VOLUME SPIKE (gratuito) ─────────────────────────────

def scan_volume_spikes(watchlist: list[str] | None = None) -> list[dict]:
    """
    Varre a watchlist e deteta volume anormal.
    Volume 4x + movimento de preço = possível mão institucional.
    """
    if watchlist is None:
        watchlist = DEFAULT_WATCHLIST

    signals = []
    log.info(f"A varrer {len(watchlist)} ações por volume anormal...")

    for ticker in watchlist:
        try:
            data = get_market_data(ticker)
            if not data:
                continue

            vol_ratio  = data.get("volume_ratio", 1)
            change_pct = data.get("change_pct", 0)
            price      = data.get("price", 0)

            # Acumulação institucional — volume alto + preço sobe
            if vol_ratio >= VOLUME_SPIKE_THRESHOLD and change_pct > PRICE_MOVE_THRESHOLD:
                strength = "extremo" if vol_ratio >= VOLUME_EXTREME_THRESHOLD else "forte"
                signals.append({
                    "ticker":     ticker,
                    "signal":     "accumulation",
                    "direction":  "bullish",
                    "vol_ratio":  round(vol_ratio, 1),
                    "change_pct": round(change_pct, 2),
                    "price":      price,
                    "strength":   strength,
                    "reason":     f"Volume {vol_ratio:.1f}x + preço +{change_pct:.1f}%",
                    "timestamp":  datetime.now().isoformat(),
                    "source":     "volume_spike",
                })
                log.warning(
                    f"🟢 ACUMULAÇÃO {ticker} | "
                    f"Vol {vol_ratio:.1f}x | +{change_pct:.1f}%"
                )

            # Distribuição institucional — volume alto + preço cai
            elif vol_ratio >= VOLUME_SPIKE_THRESHOLD and change_pct < -PRICE_MOVE_THRESHOLD:
                strength = "extremo" if vol_ratio >= VOLUME_EXTREME_THRESHOLD else "forte"
                signals.append({
                    "ticker":     ticker,
                    "signal":     "distribution",
                    "direction":  "bearish",
                    "vol_ratio":  round(vol_ratio, 1),
                    "change_pct": round(change_pct, 2),
                    "price":      price,
                    "strength":   strength,
                    "reason":     f"Volume {vol_ratio:.1f}x + preço {change_pct:.1f}%",
                    "timestamp":  datetime.now().isoformat(),
                    "source":     "volume_spike",
                })
                log.warning(
                    f"🔴 DISTRIBUIÇÃO {ticker} | "
                    f"Vol {vol_ratio:.1f}x | {change_pct:.1f}%"
                )

        except Exception as e:
            log.debug(f"{ticker}: erro no scan — {e}")

    log.info(f"Volume scan: {len(signals)} sinais detetados")
    return signals


# ── CAMADA 2: UNUSUAL OPTIONS ACTIVITY (Unusual Whales) ───────────

def get_unusual_options_flow(ticker: str | None = None) -> list[dict]:
    """
    Unusual Whales API — fluxo de opções incomum.
    Opcional — só corre se UNUSUAL_WHALES_TOKEN estiver configurado.
    """
    if not UNUSUAL_WHALES_TOKEN:
        log.debug("Unusual Whales não configurado — a saltar")
        return []

    try:
        headers = {"Authorization": f"Bearer {UNUSUAL_WHALES_TOKEN}"}
        params  = {}
        if ticker:
            params["ticker"] = ticker

        # Endpoint de flow de opções
        response = requests.get(
            "https://api.unusualwhales.com/api/option-trades/flow",
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code != 200:
            log.warning(f"Unusual Whales: {response.status_code}")
            return []

        trades = response.json().get("data", [])
        signals = []

        for t in trades:
            premium = float(t.get("premium", 0) or 0)
            if premium < UOA_MIN_PREMIUM:
                continue

            sentiment = t.get("sentiment", "neutral")
            if sentiment not in ("bullish", "bearish"):
                continue

            urgency = "alta" if premium >= UOA_LARGE_PREMIUM else "média"

            signals.append({
                "ticker":    t.get("ticker", ""),
                "signal":    "unusual_options",
                "direction": "bullish" if sentiment == "bullish" else "bearish",
                "option_type": t.get("option_type", ""),   # call ou put
                "strike":    t.get("strike", 0),
                "expiry":    t.get("expiry", ""),
                "premium":   premium,
                "premium_fmt": f"${premium/1_000_000:.1f}M" if premium >= 1_000_000 else f"${premium/1_000:.0f}K",
                "sentiment": sentiment,
                "urgency":   urgency,
                "strength":  "extremo" if premium >= UOA_LARGE_PREMIUM else "forte",
                "reason":    (
                    f"Compra de {t.get('option_type','').upper()} "
                    f"${t.get('strike')} exp {t.get('expiry')} "
                    f"— prémio ${premium/1_000:.0f}K"
                ),
                "timestamp": datetime.now().isoformat(),
                "source":    "unusual_whales",
            })

            log.warning(
                f"{'🟢' if sentiment == 'bullish' else '🔴'} UOA {t.get('ticker')} | "
                f"{t.get('option_type','').upper()} ${t.get('strike')} | "
                f"${premium/1_000:.0f}K"
            )

        return signals

    except Exception as e:
        log.error(f"Unusual Whales erro: {e}")
        return []


# ── ANÁLISE LLM DOS SINAIS ────────────────────────────────────────

def analyze_signals_with_llm(signals: list[dict]) -> list[dict]:
    """
    Para cada sinal, o LLM avalia:
    - Há notícia que explique o movimento? (se sim, menos interessante)
    - Qual a probabilidade de ser movimento institucional real?
    - Que ação sugerida? (observar, considerar entrada, evitar)
    """
    if not signals:
        return []

    enriched = []

    for signal in signals:
        try:
            prompt = f"""
Detetei um sinal de fluxo institucional potencial:

Ticker: {signal['ticker']}
Sinal: {signal['signal']}
Direção: {signal['direction']}
Razão: {signal['reason']}
Força: {signal['strength']}
Preço atual: ${signal.get('price', 'N/D')}
Fonte: {signal['source']}

Analisa este sinal e responde em JSON:
{{
    "is_institutional": true | false,
    "confidence": 0-100,
    "likely_reason": "explicação provável em 1 frase",
    "news_explained": true | false,
    "action": "observar" | "considerar_entrada" | "evitar",
    "suggested_instrument": "ações" | "call" | "put" | "covered_call" | "bear_call_spread",
    "time_horizon": "intraday" | "esta semana" | "próximas 2 semanas",
    "risk_level": "alto" | "médio" | "baixo",
    "summary": "resumo em 1 frase para notificação"
}}
"""
            analysis = ask(prompt, max_tokens=400)
            enriched.append({**signal, "llm_analysis": analysis})

        except Exception as e:
            log.warning(f"LLM análise {signal['ticker']}: {e}")
            enriched.append({**signal, "llm_analysis": {}})

    return enriched


# ── SCAN COMPLETO ─────────────────────────────────────────────────

def run_flow_scan(watchlist: list[str] | None = None,
                  portfolio_tickers: list[str] | None = None) -> list[dict]:
    """
    Scan completo:
    1. Volume spikes em toda a watchlist
    2. UOA via Unusual Whales (se configurado)
    3. Análise LLM de cada sinal
    4. Persiste resultados para o dashboard
    """
    log.info("━━ INSTITUTIONAL FLOW SCAN ━━━━━━━━━━━━━━━━")

    all_signals = []

    # Watchlist = DEFAULT + portfolio atual
    full_watchlist = list(set(
        (watchlist or DEFAULT_WATCHLIST) +
        (portfolio_tickers or [])
    ))

    # Camada 1: volume spikes
    volume_signals = scan_volume_spikes(full_watchlist)
    all_signals.extend(volume_signals)

    # Camada 2: UOA (se configurado)
    uoa_signals = get_unusual_options_flow()
    all_signals.extend(uoa_signals)

    if not all_signals:
        log.info("Nenhum sinal institucional detetado")
        return []

    # Análise LLM
    log.info(f"A analisar {len(all_signals)} sinais com LLM...")
    enriched = analyze_signals_with_llm(all_signals)

    # Filtrar apenas sinais com confiança >= 60%
    filtered = [
        s for s in enriched
        if s.get("llm_analysis", {}).get("confidence", 0) >= 60
    ]

    log.info(f"{len(filtered)} sinais relevantes após filtro LLM")

    # Persistir para dashboard
    _save_signals(filtered)

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return filtered


# ── VIX MONITOR ───────────────────────────────────────────────────

def check_vix_spike() -> dict | None:
    """
    VIX spike > 15% num dia = volatilidade extrema.
    Sinal de venda massiva institucional no mercado.
    """
    try:
        vix = get_market_data("VIX")
        if not vix:
            return None

        change = vix.get("change_pct", 0)
        price  = vix.get("price", 0)

        if change > 15:
            return {
                "ticker":    "VIX",
                "signal":    "vix_spike",
                "direction": "bearish",
                "value":     change,
                "price":     price,
                "strength":  "extremo" if change > 25 else "forte",
                "reason":    f"VIX +{change:.1f}% — volatilidade extrema",
                "urgency":   "alta",
                "timestamp": datetime.now().isoformat(),
                "source":    "vix_monitor",
                "llm_analysis": {
                    "action":  "evitar",
                    "summary": f"VIX spike {change:.0f}% — mercado em stress, evitar novas posições",
                    "risk_level": "alto",
                }
            }
    except Exception as e:
        log.warning(f"VIX check: {e}")

    return None


# ── PERSISTÊNCIA ──────────────────────────────────────────────────

def _save_signals(signals: list[dict]):
    """Guarda sinais para o dashboard."""
    Path("data").mkdir(exist_ok=True)
    path = Path("data/flow_signals.json")

    # Carregar histórico existente
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            existing = []

    # Adicionar novos (máximo 100 no histórico)
    all_signals = signals + existing
    all_signals = all_signals[:100]

    path.write_text(json.dumps({
        "updated":  datetime.now().isoformat(),
        "signals":  all_signals,
        "today_count": len(signals),
    }, indent=2))


def load_signals() -> dict:
    """Carrega sinais para o dashboard."""
    path = Path("data/flow_signals.json")
    if path.exists():
        return json.loads(path.read_text())
    return {"signals": [], "today_count": 0}
