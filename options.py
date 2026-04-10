"""
options.py — Seleção de contratos na chain de opções via IBKR.
"""

import logging
from datetime import date, timedelta
from ib_insync import IB, Option, ComboLeg, Contract, LimitOrder, MarketOrder, TagValue

log = logging.getLogger(__name__)


def get_next_friday() -> str:
    today = date.today()
    days  = (4 - today.weekday()) % 7
    if days == 0:
        days = 7
    return (today + timedelta(days=days)).strftime("%Y%m%d")


def get_this_friday() -> str:
    today = date.today()
    days  = (4 - today.weekday()) % 7
    return (today + timedelta(days=days)).strftime("%Y%m%d")


def days_to_expiry(expiry_yyyymmdd: str) -> int:
    exp = date.fromisoformat(
        f"{expiry_yyyymmdd[:4]}-{expiry_yyyymmdd[4:6]}-{expiry_yyyymmdd[6:]}"
    )
    return max(0, (exp - date.today()).days)


def get_chain(ib: IB, ticker: str) -> object | None:
    """Obtém a chain de opções do IBKR."""
    try:
        chains = ib.reqSecDefOptParams(ticker, "", "STK", 0)
        if not chains:
            log.warning(f"{ticker}: sem chain de opções")
            return None
        # Preferir a chain com o próprio ticker como tradingClass
        for c in chains:
            if c.tradingClass == ticker:
                return c
        return chains[0]
    except Exception as e:
        log.error(f"{ticker}: erro a obter chain — {e}")
        return None


def find_strike(ib: IB, ticker: str, spot: float,
                expiry: str, config) -> dict | None:
    """
    Encontra o melhor strike para covered call ou spread.
    Devolve dict com contrato, strike, prémio, delta, yield.
    """
    chain = get_chain(ib, ticker)
    if not chain:
        return None

    # Strikes OTM: entre spot*(1+otm/2) e spot*(1+otm*3)
    lo = spot * (1 + config.target_otm_pct / 2)
    hi = spot * (1 + config.target_otm_pct * 3)
    candidates = sorted([s for s in chain.strikes if lo < s <= hi])

    if not candidates:
        log.warning(f"{ticker}: sem strikes OTM em [{lo:.2f},{hi:.2f}]")
        return None

    for strike in candidates:
        contract = Option(ticker, expiry, strike, "C", "SMART")
        try:
            ib.qualifyContracts(contract)
        except Exception:
            continue

        ticker_mkt = ib.reqMktData(contract, "106", False, False)
        ib.sleep(1.5)

        bid = ticker_mkt.bid or 0
        ask = ticker_mkt.ask or 0
        ib.cancelMktData(contract)

        if bid < config.min_premium:
            continue

        spread_pct = (ask - bid) / ask if ask > 0 else 1
        if spread_pct > config.max_spread_pct:
            continue

        dte        = days_to_expiry(expiry)
        annualized = (bid / spot) * (365 / max(dte, 1))
        if annualized < config.min_annualized_yield:
            continue

        delta = abs(ticker_mkt.modelGreeks.delta) if ticker_mkt.modelGreeks else None

        log.info(
            f"{ticker} strike ${strike} | bid ${bid:.2f} | "
            f"yield {annualized:.1%} | delta {delta}"
        )

        return {
            "contract":         contract,
            "strike":           strike,
            "expiry":           expiry,
            "bid":              bid,
            "ask":              ask,
            "premium":          bid,       # vendemos ao bid (conservador)
            "delta":            delta,
            "annualized_yield": annualized,
            "dte":              dte,
        }

    log.warning(f"{ticker}: nenhum strike passou os filtros")
    return None


# ── COVERED CALL ──────────────────────────────────────────────────

def open_covered_call(ib: IB, ticker: str, spot: float,
                      expiry: str, config) -> dict | None:
    """Vende 1 call coberta. Devolve dict com detalhes ou None."""
    data = find_strike(ib, ticker, spot, expiry, config)
    if not data:
        return None

    order = LimitOrder("SELL", 1, round(data["premium"], 2))
    ib.placeOrder(data["contract"], order)
    ib.sleep(3)

    result = {**data, "strategy": "covered_call",
              "net_credit": data["premium"], "long_strike": None}
    log.info(
        f"{ticker} COVERED CALL aberta | "
        f"Strike ${data['strike']} exp {expiry} | "
        f"Prémio ${data['premium']*100:.0f}"
    )
    return result


def close_covered_call(ib: IB, position: dict) -> float:
    """Fecha covered call. Devolve preço de fecho."""
    ticker_mkt = ib.reqMktData(position["contract"], "", False, False)
    ib.sleep(1.5)
    close_price = ticker_mkt.ask or position["net_credit"]
    ib.cancelMktData(position["contract"])

    order = LimitOrder("BUY", 1, round(close_price, 2))
    ib.placeOrder(position["contract"], order)
    ib.sleep(3)

    pnl = (position["net_credit"] - close_price) * 100
    log.info(
        f"{position['ticker']} CC fechada @ ${close_price:.2f} | "
        f"P&L ${pnl:+.0f}"
    )
    return close_price


# ── BEAR CALL SPREAD ──────────────────────────────────────────────

def open_bear_call_spread(ib: IB, ticker: str, spot: float,
                           expiry: str, config) -> dict | None:
    """Abre bear call spread como combo order."""
    short_data = find_strike(ib, ticker, spot, expiry, config)
    if not short_data:
        return None

    chain = get_chain(ib, ticker)
    if not chain:
        return None

    # Strike da perna longa
    long_strike_target = short_data["strike"] + config.spread_width
    long_strike = min(
        [s for s in chain.strikes if s > short_data["strike"]],
        key=lambda s: abs(s - long_strike_target),
        default=None
    )
    if not long_strike:
        return None

    long_contract = Option(ticker, expiry, long_strike, "C", "SMART")
    try:
        ib.qualifyContracts(long_contract)
    except Exception as e:
        log.error(f"{ticker}: erro a qualificar long strike — {e}")
        return None

    long_ticker = ib.reqMktData(long_contract, "", False, False)
    ib.sleep(1.5)
    long_ask = long_ticker.ask or 0
    ib.cancelMktData(long_contract)

    net_credit = short_data["bid"] - long_ask
    if net_credit < config.min_net_credit:
        log.warning(
            f"{ticker}: crédito líquido ${net_credit:.2f} < "
            f"mínimo ${config.min_net_credit:.2f}"
        )
        return None

    # Combo order (as duas pernas em simultâneo)
    bag             = Contract()
    bag.symbol      = ticker
    bag.secType     = "BAG"
    bag.currency    = "USD"
    bag.exchange    = "SMART"

    short_leg          = ComboLeg()
    short_leg.conId    = short_data["contract"].conId
    short_leg.ratio    = 1
    short_leg.action   = "SELL"
    short_leg.exchange = "SMART"

    long_leg           = ComboLeg()
    long_leg.conId     = long_contract.conId
    long_leg.ratio     = 1
    long_leg.action    = "BUY"
    long_leg.exchange  = "SMART"

    bag.comboLegs = [short_leg, long_leg]

    order = LimitOrder("SELL", 1, round(net_credit, 2))
    order.smartComboRoutingParams = [TagValue("NonGuaranteed", "1")]
    ib.placeOrder(bag, order)
    ib.sleep(3)

    max_loss   = (config.spread_width - net_credit) * 100
    max_profit = net_credit * 100
    breakeven  = short_data["strike"] + net_credit

    log.info(
        f"{ticker} BEAR CALL SPREAD aberto | "
        f"${short_data['strike']}/${long_strike} exp {expiry} | "
        f"Crédito ${net_credit*100:.0f} | Max loss ${max_loss:.0f}"
    )

    return {
        "strategy":      "bear_call_spread",
        "contract":      bag,
        "short_contract": short_data["contract"],
        "long_contract": long_contract,
        "strike":        short_data["strike"],
        "short_strike":  short_data["strike"],
        "long_strike":   long_strike,
        "expiry":        expiry,
        "net_credit":    net_credit,
        "max_loss":      max_loss,
        "max_profit":    max_profit,
        "breakeven":     breakeven,
        "delta":         short_data.get("delta"),
        "annualized_yield": short_data["annualized_yield"],
        "dte":           short_data["dte"],
    }


def close_bear_call_spread(ib: IB, position: dict) -> float:
    """Fecha spread como combo order."""
    close_order = MarketOrder("BUY", 1)
    ib.placeOrder(position["contract"], close_order)
    ib.sleep(3)

    log.info(
        f"{position['ticker']} BCS fechado | "
        f"${position['short_strike']}/${position['long_strike']}"
    )
    return 0.0  # market order — preço real vem do fill


# ── ROLL ──────────────────────────────────────────────────────────

def roll_position(ib: IB, position: dict, spot: float,
                  config, ticker: str) -> dict | None:
    """Fecha posição atual e abre nova para semana seguinte."""
    log.info(f"━━ ROLL {ticker} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Fechar
    if position["strategy"] == "covered_call":
        close_price = close_covered_call(ib, position)
    else:
        close_price = close_bear_call_spread(ib, position)

    # Abrir semana seguinte
    expiry = get_next_friday()

    if position["strategy"] == "covered_call":
        new_pos = open_covered_call(ib, ticker, spot, expiry, config)
    else:
        new_pos = open_bear_call_spread(ib, ticker, spot, expiry, config)

    if new_pos:
        new_pos["ticker"] = ticker
        net = new_pos["net_credit"] * 100
        log.info(f"Roll completo | Crédito líquido ${net:.0f}")

    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return new_pos
