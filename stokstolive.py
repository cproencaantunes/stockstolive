"""
agent_manager.py — Orquestrador principal do agente.
Gere o portfolio completo: rolls semanais, monitorização e research.
"""

import logging, json
from datetime import date, datetime
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from ib_insync import IB

from config import IBKR_HOST, IBKR_PORT, IBKR_CLIENT, TIMEZONE, DEFAULT_PORTFOLIO
from portfolio import Portfolio, Position
from analysis import select_strategy, run_evening_analysis, run_premarket_analysis
from options import roll_position, open_covered_call, open_bear_call_spread, get_next_friday
from data import get_market_data, get_market_overview, get_top_movers, get_premarket_data
from notifications import send_email_report, send_push_notification

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/agent.log"),
    ]
)
log = logging.getLogger(__name__)

# Estado global
ib        = IB()
portfolio = Portfolio()

# Portfolio config — carregado do ficheiro ou defaults
def load_portfolio_config() -> dict:
    path = Path("data/portfolio_config.json")
    if path.exists():
        try:
            from config import StockConfig
            raw = json.loads(path.read_text())
            return {k: StockConfig(**v) for k, v in raw.items()}
        except Exception as e:
            log.warning(f"Erro ao carregar config: {e} — usando defaults")
    return DEFAULT_PORTFOLIO.copy()


def save_portfolio_config(config: dict):
    from dataclasses import asdict
    Path("data").mkdir(exist_ok=True)
    Path("data/portfolio_config.json").write_text(
        json.dumps({k: asdict(v) for k, v in config.items()}, indent=2)
    )


# ── IBKR ──────────────────────────────────────────────────────────

def connect_ibkr():
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT)
        log.info(f"IBKR ligado em {IBKR_HOST}:{IBKR_PORT}")
    except Exception as e:
        log.error(f"Erro a ligar ao IBKR: {e}")
        raise


def ensure_connected():
    if not ib.isConnected():
        log.warning("IBKR desligado — a reconectar")
        connect_ibkr()


# ── ROLL SEMANAL ──────────────────────────────────────────────────

def friday_roll_all():
    """Sexta 15h30 ET — roll de todo o portfolio."""
    ensure_connected()
    config_map = load_portfolio_config()

    log.info("━━ ROLL SEMANAL — PORTFOLIO COMPLETO ━━━━━━━━")

    for ticker, config in config_map.items():

        # Ignorar tickers marcados para remoção — deixar expirar
        if ticker in portfolio.removing_positions:
            log.info(f"{ticker} — marcado para expirar, a saltar roll")
            continue

        log.info(f"── {ticker} ──────────────────────────────")

        try:
            data = get_market_data(ticker)
            if not data:
                log.warning(f"{ticker} — sem dados, a saltar")
                continue
            spot = data["price"]

            # Reavaliar estratégia esta semana
            decision = select_strategy(ticker, config)

            if ticker in portfolio.positions:
                # Roll — fecha atual e abre nova
                new_pos = roll_position(
                    ib, portfolio.positions[ticker],
                    spot, config, ticker
                )
            else:
                # Primeira vez — só abre
                expiry = get_next_friday()
                if decision.strategy == "covered_call":
                    new_pos = open_covered_call(ib, ticker, spot, expiry, config)
                else:
                    new_pos = open_bear_call_spread(ib, ticker, spot, expiry, config)

            if new_pos:
                portfolio.add_position(Position(
                    ticker       = ticker,
                    strategy     = new_pos["strategy"],
                    short_strike = new_pos["short_strike"],
                    long_strike  = new_pos.get("long_strike"),
                    expiry       = new_pos["expiry"],
                    net_credit   = new_pos["net_credit"],
                    max_loss     = new_pos.get("max_loss"),
                    opened_at    = date.today().isoformat(),
                    iv_at_open   = decision.iv,
                ))

        except Exception as e:
            log.error(f"{ticker} — erro no roll: {e}")

    # Resumo
    log.info("━━ RESUMO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info(f"Posições ativas: {len(portfolio.active_positions)}")
    log.info(f"Prémio semanal: ${portfolio.weekly_premium:.0f}")
    log.info(f"Acumulado total: ${portfolio.total_premium_collected:.0f}")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Notificar
    try:
        send_push_notification(
            f"Roll semanal completo | ${portfolio.weekly_premium:.0f}/semana | "
            f"{len(portfolio.active_positions)} posições"
        )
    except Exception:
        pass


# ── ROLL ANTECIPADO (NOVA AÇÃO ADICIONADA A MID-WEEK) ─────────────

def open_new_position(ticker: str):
    """Abre posição imediatamente para ação recém adicionada."""
    ensure_connected()
    config_map = load_portfolio_config()

    if ticker not in config_map:
        log.error(f"{ticker} não encontrado na config")
        return

    config = config_map[ticker]
    data   = get_market_data(ticker)
    if not data:
        log.error(f"{ticker}: sem dados de mercado")
        return

    spot     = data["price"]
    decision = select_strategy(ticker, config)
    expiry   = get_next_friday()

    if decision.strategy == "covered_call":
        new_pos = open_covered_call(ib, ticker, spot, expiry, config)
    else:
        new_pos = open_bear_call_spread(ib, ticker, spot, expiry, config)

    if new_pos:
        portfolio.add_position(Position(
            ticker       = ticker,
            strategy     = new_pos["strategy"],
            short_strike = new_pos["short_strike"],
            long_strike  = new_pos.get("long_strike"),
            expiry       = new_pos["expiry"],
            net_credit   = new_pos["net_credit"],
            max_loss     = new_pos.get("max_loss"),
            opened_at    = date.today().isoformat(),
            iv_at_open   = decision.iv,
        ))
        log.info(f"{ticker} — posição aberta mid-week")


# ── MONITORIZAÇÃO ─────────────────────────────────────────────────

def daily_monitor():
    """Terça a quinta — verifica posições abertas."""
    ensure_connected()

    for ticker, pos in list(portfolio.active_positions.items()):
        config_map = load_portfolio_config()
        config     = config_map.get(ticker)
        if not config:
            continue

        try:
            data = get_market_data(ticker)
            if not data:
                continue
            spot = data["price"]

            # Cotação atual da short call
            ticker_mkt = ib.reqMktData(pos.contract if hasattr(pos, 'contract')
                                       else None, "", False, False)
            ib.sleep(1.5)
            current = ticker_mkt.ask or pos.net_credit if ticker_mkt else pos.net_credit
            ib.cancelMktData(ticker_mkt.contract if ticker_mkt else None)

            profit_pct   = 1 - (current / pos.net_credit)
            itm_distance = (pos.short_strike - spot) / spot

            log.info(
                f"{ticker} | ${spot:.2f} | "
                f"Strike ${pos.short_strike} ({itm_distance:+.1%}) | "
                f"P&L: {profit_pct:.0%}"
            )

            # Roll antecipado
            if profit_pct >= config.early_roll_at:
                log.info(f"{ticker} — roll antecipado ({profit_pct:.0%} capturado)")
                new_pos = roll_position(ib, pos, spot, config, ticker)
                if new_pos:
                    portfolio.add_position(Position(
                        ticker       = ticker,
                        strategy     = new_pos["strategy"],
                        short_strike = new_pos["short_strike"],
                        long_strike  = new_pos.get("long_strike"),
                        expiry       = new_pos["expiry"],
                        net_credit   = new_pos["net_credit"],
                        max_loss     = new_pos.get("max_loss"),
                        opened_at    = date.today().isoformat(),
                        iv_at_open   = 0.0,
                    ))

            # Alerta de proximidade
            elif itm_distance < config.alert_itm_distance:
                msg = (f"⚠️ {ticker} a {itm_distance:.1%} do strike "
                       f"${pos.short_strike}")
                log.warning(msg)
                send_push_notification(msg)

        except Exception as e:
            log.error(f"Monitor {ticker}: {e}")


# ── RESEARCH ──────────────────────────────────────────────────────

def evening_research():
    """18h00 ET — análise após fecho."""
    log.info("=== RESEARCH APÓS FECHO ===")
    try:
        market   = get_market_overview()
        movers   = get_top_movers()
        tickers  = list(portfolio.active_positions.keys())
        analysis = run_evening_analysis(market, movers, tickers)

        # Guardar para o dashboard
        Path("data").mkdir(exist_ok=True)
        Path("data/evening_research.json").write_text(
            json.dumps({"date": date.today().isoformat(),
                        "analysis": analysis}, indent=2)
        )
        send_email_report(analysis)
        log.info(f"Research: {len(analysis.get('opportunities',[]))} oportunidades")
    except Exception as e:
        log.error(f"Evening research: {e}")


def premarket_briefing():
    """08h30 ET — briefing pré-abertura."""
    log.info("=== BRIEFING PRÉ-ABERTURA ===")
    try:
        premarket = get_premarket_data("SPY")
        futures   = get_premarket_data("ES=F")

        evening = {}
        p = Path("data/evening_research.json")
        if p.exists():
            evening = json.loads(p.read_text()).get("analysis", {})

        briefing = run_premarket_analysis(premarket, futures, evening)

        Path("data/premarket_briefing.json").write_text(
            json.dumps({"date": date.today().isoformat(),
                        "briefing": briefing}, indent=2)
        )
        send_push_notification(briefing.get("summary", "Briefing disponível"))
    except Exception as e:
        log.error(f"Premarket briefing: {e}")


# ── SCHEDULER ─────────────────────────────────────────────────────

def start():
    connect_ibkr()

    scheduler = BlockingScheduler(timezone=TIMEZONE)

    # Roll semanal — sexta 15h30 ET
    scheduler.add_job(friday_roll_all, "cron",
                      day_of_week="fri", hour=15, minute=30,
                      id="weekly_roll")

    # Monitor — terça a quinta, de hora em hora
    scheduler.add_job(daily_monitor, "cron",
                      day_of_week="tue-thu", hour="10-15", minute=0,
                      id="daily_monitor")

    # Research após fecho — todos os dias úteis
    scheduler.add_job(evening_research, "cron",
                      day_of_week="mon-fri", hour=18, minute=0,
                      id="evening_research")

    # Briefing pré-abertura
    scheduler.add_job(premarket_briefing, "cron",
                      day_of_week="tue-sat", hour=8, minute=30,
                      id="premarket_briefing")

    log.info("━━ TRADING AGENT INICIADO ━━━━━━━━━━━━━━━━━━")
    log.info(f"Provider LLM: {__import__('config').LLM_PROVIDER}")
    log.info(f"Modelo: {__import__('config').LLM_MODEL}")
    log.info(f"IBKR modo: {__import__('config').IBKR_MODE}")
    log.info(f"Portfolio: {list(load_portfolio_config().keys())}")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    scheduler.start()


if __name__ == "__main__":
    start()
