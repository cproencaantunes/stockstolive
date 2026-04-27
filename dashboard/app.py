"""
dashboard/app.py — Flask backend com API para gestão do portfolio.
Serve o dashboard HTML e expõe endpoints para adicionar/remover ações.
"""

import os, json, logging
from datetime import date
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from dataclasses import asdict
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from portfolio import Portfolio
from config import StockConfig, DEFAULT_PORTFOLIO

app       = Flask(__name__, static_folder="static")
portfolio = Portfolio()
log       = logging.getLogger(__name__)

PORTFOLIO_CONFIG_PATH = Path("data/portfolio_config.json")


def load_config() -> dict:
    if PORTFOLIO_CONFIG_PATH.exists():
        raw = json.loads(PORTFOLIO_CONFIG_PATH.read_text())
        return {k: StockConfig(**v) for k, v in raw.items()}
    return DEFAULT_PORTFOLIO.copy()


def save_config(cfg: dict):
    PORTFOLIO_CONFIG_PATH.parent.mkdir(exist_ok=True)
    PORTFOLIO_CONFIG_PATH.write_text(
        json.dumps({k: asdict(v) for k, v in cfg.items()}, indent=2)
    )


# ── DASHBOARD ─────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(
        os.path.dirname(os.path.abspath(__file__)),
        "index.html"
    )


# ── API — ESTADO ──────────────────────────────────────────────────

@app.route("/api/portfolio")
def get_portfolio():
    """Estado completo do portfolio para o dashboard."""
    cfg = load_config()
    positions = []
    for ticker, pos in portfolio.positions.items():
        from data import get_market_data, get_implied_volatility
        data     = get_market_data(ticker)
        iv, rank = get_implied_volatility(ticker)
        positions.append({
            **asdict(pos),
            "price":   data.get("price", 0),
            "iv":      iv,
            "iv_rank": rank,
            "change_pct": data.get("change_pct", 0),
        })
    return jsonify({
        "positions": positions,
        "summary":   portfolio.summary(),
        "config":    {k: asdict(v) for k, v in cfg.items()},
        "date":      date.today().isoformat(),
    })


@app.route("/api/history")
def get_history():
    return jsonify([asdict(h) for h in portfolio.history])


@app.route("/api/research")
def get_research():
    p = Path("data/evening_research.json")
    if p.exists():
        return jsonify(json.loads(p.read_text()))
    return jsonify({"opportunities": [], "market_summary": "Sem dados ainda"})


@app.route("/api/flow-signals")
def get_flow_signals():
    """Sinais de fluxo institucional para o dashboard."""
    from institutional_flow import load_signals
    return jsonify(load_signals())


@app.route("/api/briefing")
def get_briefing():
    p = Path("data/premarket_briefing.json")
    if p.exists():
        return jsonify(json.loads(p.read_text()))
    return jsonify({"briefing": {}})


# ── API — GESTÃO DO PORTFOLIO ─────────────────────────────────────

@app.route("/api/portfolio/add", methods=["POST"])
def add_stock():
    """
    Adiciona ação ao portfolio.
    Body JSON: { ticker, shares, target_otm_pct, min_premium,
                 spread_width, strategy_override }
    """
    body = request.get_json()
    if not body or not body.get("ticker"):
        return jsonify({"error": "ticker obrigatório"}), 400

    ticker  = body["ticker"].upper().strip()
    cfg     = load_config()

    if ticker in cfg:
        return jsonify({"error": f"{ticker} já está no portfolio"}), 409

    # Criar config com valores do request ou defaults
    new_cfg = StockConfig(
        ticker            = ticker,
        shares            = int(body.get("shares", 100)),
        target_otm_pct    = float(body.get("target_otm_pct", 0.02)),
        min_premium       = float(body.get("min_premium", 0.75)),
        spread_width      = float(body.get("spread_width", 5.0)),
        strategy_override = body.get("strategy_override", "auto"),
    )

    cfg[ticker] = new_cfg
    save_config(cfg)

    log.info(f"Ação adicionada ao portfolio: {ticker}")

    # Disparar abertura de posição se dentro do horário de mercado
    # (em produção: chamar agent_manager.open_new_position(ticker) em thread)
    try:
        from datetime import datetime
        import pytz
        now_et = datetime.now(pytz.timezone("America/New_York"))
        market_open = now_et.weekday() < 5 and 9 <= now_et.hour < 15
        if market_open:
            import threading
            from stockstolive import open_new_position
            t = threading.Thread(target=open_new_position, args=(ticker,), daemon=True)
            t.start()
            msg = f"{ticker} adicionado — posição a abrir no mercado"
        else:
            msg = f"{ticker} adicionado — posição abre na próxima sexta 15h30 ET"
    except Exception:
        msg = f"{ticker} adicionado ao portfolio"

    return jsonify({"ok": True, "message": msg, "config": asdict(new_cfg)})


@app.route("/api/portfolio/remove", methods=["POST"])
def remove_stock():
    """
    Marca ação para não renovar.
    Posição atual expira normalmente na sexta.
    Body JSON: { ticker }
    """
    body   = request.get_json()
    ticker = (body or {}).get("ticker", "").upper().strip()

    if not ticker:
        return jsonify({"error": "ticker obrigatório"}), 400

    cfg = load_config()

    # Remover da config (sem novas posições após esta)
    if ticker in cfg:
        del cfg[ticker]
        save_config(cfg)

    # Marcar posição atual para não renovar
    if ticker in portfolio.positions:
        portfolio.mark_removing(ticker)
        msg = (f"{ticker} marcado para expirar — "
               f"posição atual não será renovada na próxima sexta")
    else:
        msg = f"{ticker} removido do portfolio (sem posição aberta)"

    log.info(msg)
    return jsonify({"ok": True, "message": msg})


@app.route("/api/portfolio/update", methods=["POST"])
def update_stock():
    """Atualiza parâmetros de uma ação existente."""
    body   = request.get_json()
    ticker = (body or {}).get("ticker", "").upper().strip()

    if not ticker:
        return jsonify({"error": "ticker obrigatório"}), 400

    cfg = load_config()
    if ticker not in cfg:
        return jsonify({"error": f"{ticker} não encontrado"}), 404

    current = asdict(cfg[ticker])
    for k, v in body.items():
        if k != "ticker" and k in current:
            current[k] = v

    cfg[ticker] = StockConfig(**current)
    save_config(cfg)

    return jsonify({"ok": True, "config": asdict(cfg[ticker])})


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "date":   date.today().isoformat(),
        "positions": len(portfolio.positions),
        "provider": __import__("config").LLM_PROVIDER,
        "model":    __import__("config").LLM_MODEL,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__("os").getenv("PORT", 8080)),
            debug=False)
