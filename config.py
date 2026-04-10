"""
config.py — Configuração central do agente
Todos os parâmetros vêm de variáveis de ambiente.
Para mudar de Gemini → Claude: só mudar LLM_PROVIDER e LLM_MODEL no Railway.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

# ── LLM ───────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")   # "gemini" ou "claude"
LLM_MODEL    = os.getenv("LLM_MODEL",    "gemini-2.0-flash")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── IBKR ──────────────────────────────────────────────────────────
IBKR_HOST     = os.getenv("IBKR_HOST",         "127.0.0.1")
IBKR_PORT     = int(os.getenv("IBKR_PORT",     "7497"))   # 7497=TWS paper / 4001=Gateway
IBKR_CLIENT   = int(os.getenv("IBKR_CLIENT",   "1"))
IBKR_MODE     = os.getenv("IBKR_TRADING_MODE", "paper")   # "paper" ou "live"

# ── NOTIFICAÇÕES ──────────────────────────────────────────────────
EMAIL_FROM     = os.getenv("EMAIL_FROM",     "")
EMAIL_TO       = os.getenv("EMAIL_TO",       "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
PUSHOVER_APP   = os.getenv("PUSHOVER_APP",   "")
PUSHOVER_USER  = os.getenv("PUSHOVER_USER",  "")

# ── AMBIENTE ──────────────────────────────────────────────────────
ENV            = os.getenv("RAILWAY_ENV", "development")
TIMEZONE       = "America/New_York"
DATA_DIR       = "data"
LOG_LEVEL      = os.getenv("LOG_LEVEL", "INFO")

# ── STOCK CONFIG ──────────────────────────────────────────────────
@dataclass
class StockConfig:
    ticker:               str
    shares:               int   = 100
    target_otm_pct:       float = 0.02    # strike 2% acima do spot
    min_premium:          float = 0.50    # prémio mínimo por ação
    min_annualized_yield: float = 0.10    # yield mínimo anualizado
    max_spread_pct:       float = 0.15    # spread bid/ask máximo
    spread_width:         float = 5.0     # largura do spread em $
    min_net_credit:       float = 0.75    # crédito líquido mínimo
    early_roll_at:        float = 0.80    # roll antecipado a 80% do prémio
    alert_itm_distance:   float = 0.01    # alerta se <1% do strike
    strategy_override:    str   = "auto"  # "auto","covered_call","bear_call_spread"

# Portfolio inicial — editável pelo dashboard em runtime
DEFAULT_PORTFOLIO = {
    "NVDA": StockConfig(
        ticker          = "NVDA",
        target_otm_pct  = 0.03,
        min_premium     = 2.00,
        spread_width    = 10.0,
        min_net_credit  = 1.50,
        early_roll_at   = 0.75,
    ),
    "TSLA": StockConfig(
        ticker          = "TSLA",
        target_otm_pct  = 0.04,
        min_premium     = 1.50,
        spread_width    = 5.0,
        min_net_credit  = 1.00,
        early_roll_at   = 0.70,
    ),
    "VRT": StockConfig(
        ticker          = "VRT",
        target_otm_pct  = 0.02,
        min_premium     = 0.50,
        spread_width    = 2.5,
        min_net_credit  = 0.35,
    ),
    "CRWV": StockConfig(
        ticker          = "CRWV",
        target_otm_pct  = 0.05,
        min_premium     = 0.75,
        spread_width    = 2.5,
        min_net_credit  = 0.50,
        early_roll_at   = 0.65,
    ),
}
