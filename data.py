"""
data.py — Dados de mercado, indicadores técnicos e pre-market.
"""

import yfinance as yf
import numpy as np
import logging
from datetime import date, datetime

log = logging.getLogger(__name__)


def get_market_data(ticker: str) -> dict:
    """Preço atual + indicadores técnicos."""
    try:
        df = yf.download(ticker, period="60d", interval="15m",
                         progress=False, auto_adjust=True)
        if df.empty:
            log.warning(f"{ticker}: sem dados")
            return {}

        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        vol   = df["Volume"].squeeze()

        # RSI 14
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, float("inf"))
        rsi   = (100 - 100 / (1 + rs)).iloc[-1]

        # Médias móveis
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]

        # VWAP intraday (últimas 26 velas × 15min ≈ 6.5h)
        typical = (high + low + close) / 3
        vwap    = (
            (typical * vol).rolling(26).sum() /
            vol.rolling(26).sum()
        ).iloc[-1]

        # ATR 14
        atr = (high - low).rolling(14).mean().iloc[-1]

        # Volume ratio
        vol_last = vol.iloc[-1]
        vol_avg  = vol.rolling(20).mean().iloc[-1]

        # Preço de fecho anterior (diário)
        daily = yf.download(ticker, period="3d", interval="1d",
                            progress=False, auto_adjust=True)
        prev_close = float(daily["Close"].squeeze().iloc[-2]) if len(daily) >= 2 else float(close.iloc[-1])

        price = float(close.iloc[-1])

        return {
            "ticker":       ticker,
            "price":        round(price, 2),
            "prev_close":   round(prev_close, 2),
            "change_pct":   round((price - prev_close) / prev_close * 100, 2),
            "rsi_14":       round(float(rsi), 1),
            "ma20":         round(float(ma20), 2),
            "ma50":         round(float(ma50), 2),
            "vwap":         round(float(vwap), 2),
            "atr_14":       round(float(atr), 2),
            "above_ma20":   bool(price > ma20),
            "above_ma50":   bool(price > ma50),
            "above_vwap":   bool(price > vwap),
            "ma_bullish":   bool(ma20 > ma50),
            "volume_ratio": round(float(vol_last / vol_avg) if vol_avg > 0 else 1, 2),
            "timestamp":    datetime.now().isoformat(),
        }
    except Exception as e:
        log.error(f"{ticker}: erro ao obter dados — {e}")
        return {}


def get_implied_volatility(ticker: str) -> tuple[float, float]:
    """
    IV aproximada via volatilidade histórica realizada (HV).
    Para IV real usa dados de opções do IBKR (ver options.py).
    Devolve (iv_anual, iv_rank_0_100).
    """
    try:
        stock = yf.Ticker(ticker)
        hist  = stock.history(period="1y")
        if len(hist) < 30:
            return 0.40, 50.0

        returns   = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
        hv_annual = returns.std() * np.sqrt(252)

        rolling   = returns.rolling(30).std() * np.sqrt(252)
        hv_min    = rolling.min()
        hv_max    = rolling.max()
        iv_rank   = (
            float((hv_annual - hv_min) / (hv_max - hv_min) * 100)
            if hv_max > hv_min else 50.0
        )

        return round(float(hv_annual), 3), round(iv_rank, 1)
    except Exception as e:
        log.warning(f"{ticker}: erro IV — {e}")
        return 0.40, 50.0


def get_market_overview() -> dict:
    """Snapshot dos principais índices para o research diário."""
    indices = {
        "SPY": "S&P 500", "QQQ": "Nasdaq", "IWM": "Russell 2000",
        "VIX": "Volatilidade", "GLD": "Ouro", "TLT": "Obrigações 20Y",
    }
    overview = {}
    for ticker, name in indices.items():
        try:
            df = yf.download(ticker, period="5d", interval="1d",
                             progress=False, auto_adjust=True)
            if len(df) >= 2:
                close     = float(df["Close"].squeeze().iloc[-1])
                prev      = float(df["Close"].squeeze().iloc[-2])
                chg       = (close - prev) / prev * 100
                chg5d     = (close - float(df["Close"].squeeze().iloc[0])) / float(df["Close"].squeeze().iloc[0]) * 100
                overview[ticker] = {
                    "name": name, "close": round(close, 2),
                    "change_1d": round(chg, 2),
                    "change_5d": round(chg5d, 2),
                }
        except Exception:
            pass
    return overview


def get_top_movers(watchlist: list[str] | None = None) -> dict:
    """Top gainers, losers e high volume do dia."""
    if watchlist is None:
        watchlist = [
            "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","AMD",
            "NFLX","CRM","PLTR","ARM","SMCI","COIN","XOM","JPM","LLY",
        ]
    movers = []
    for ticker in watchlist:
        try:
            df = yf.download(ticker, period="2d", interval="1d",
                             progress=False, auto_adjust=True)
            if len(df) >= 2:
                close  = float(df["Close"].squeeze().iloc[-1])
                prev   = float(df["Close"].squeeze().iloc[-2])
                chg    = (close - prev) / prev * 100
                vol    = float(df["Volume"].squeeze().iloc[-1])
                avg_v  = float(df["Volume"].squeeze().mean())
                movers.append({
                    "ticker": ticker, "close": round(close, 2),
                    "change_pct": round(chg, 2),
                    "vol_ratio":  round(vol / avg_v if avg_v > 0 else 1, 2),
                })
        except Exception:
            pass

    movers.sort(key=lambda x: x["change_pct"], reverse=True)
    return {
        "gainers":     movers[:5],
        "losers":      movers[-5:],
        "high_volume": sorted(movers, key=lambda x: x["vol_ratio"], reverse=True)[:5],
    }


def get_premarket_data(symbol: str = "SPY") -> dict:
    """Dados de pre-market (04h00–09h30 ET)."""
    try:
        ticker = yf.Ticker(symbol)
        df     = ticker.history(period="1d", interval="1m", prepost=True)
        pm     = df.between_time("04:00", "09:29")
        if pm.empty:
            return {"available": False}

        last       = float(pm["Close"].iloc[-1])
        prev_close = float(ticker.info.get("previousClose", last))
        gap        = (last - prev_close) / prev_close * 100

        return {
            "available":    True,
            "price":        round(last, 2),
            "prev_close":   round(prev_close, 2),
            "gap_pct":      round(gap, 2),
            "gap_direction": "up" if gap > 0 else "down",
            "volume":       int(pm["Volume"].sum()),
            "high":         round(float(pm["High"].max()), 2),
            "low":          round(float(pm["Low"].min()), 2),
        }
    except Exception as e:
        log.warning(f"Premarket {symbol}: {e}")
        return {"available": False}
