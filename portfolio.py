"""
portfolio.py — Gestão de estado do portfolio.
Persiste em data/portfolio.json e sincroniza com GitHub.
"""

import json, logging, subprocess
from datetime import date
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional

log = logging.getLogger(__name__)
DATA_DIR = Path("data")


@dataclass
class Position:
    ticker:        str
    strategy:      str            # "covered_call" | "bear_call_spread"
    short_strike:  float
    long_strike:   Optional[float]
    expiry:        str            # YYYYMMDD
    net_credit:    float          # por ação
    max_loss:      Optional[float]
    opened_at:     str
    iv_at_open:    float
    contracts:     int  = 1
    removing:      bool = False   # marcado para não renovar

    @property
    def max_profit(self) -> float:
        return self.net_credit * 100 * self.contracts

    @property
    def strikes_label(self) -> str:
        if self.long_strike:
            return f"${self.short_strike}/${self.long_strike}"
        return f"${self.short_strike}"


@dataclass
class HistoryEntry:
    ticker:      str
    strategy:    str
    short_strike: float
    long_strike:  Optional[float]
    expiry:      str
    opened_at:   str
    closed_at:   str
    net_credit:  float
    close_price: float
    pnl:         float
    reason:      str   # "roll", "early_roll", "expired", "manual"


class Portfolio:

    def __init__(self, path: str = "data/portfolio.json"):
        self.path      = Path(path)
        self.positions: dict[str, Position] = {}
        self.history:   list[HistoryEntry]  = []
        self._load()

    def _load(self):
        DATA_DIR.mkdir(exist_ok=True)
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text())
                self.positions = {
                    k: Position(**v)
                    for k, v in raw.get("positions", {}).items()
                }
                self.history = [
                    HistoryEntry(**h)
                    for h in raw.get("history", [])
                ]
                log.info(f"Portfolio carregado: {list(self.positions.keys())}")
            except Exception as e:
                log.error(f"Erro ao carregar portfolio: {e}")

    def save(self, push_to_github: bool = True):
        """Persiste em JSON e opcionalmente faz push para GitHub."""
        DATA_DIR.mkdir(exist_ok=True)
        data = {
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "history":   [asdict(h) for h in self.history],
            "updated":   date.today().isoformat(),
            "summary": {
                "active":          len(self.active_positions),
                "weekly_premium":  self.weekly_premium,
                "total_collected": self.total_premium_collected,
                "total_pnl":       self.total_pnl,
            }
        }
        self.path.write_text(json.dumps(data, indent=2))
        log.debug("Portfolio guardado")

        if push_to_github:
            self._git_push()

    def _git_push(self):
        """Sincroniza estado com GitHub para não perder dados."""
        try:
            subprocess.run(["git", "add", str(self.path)], check=True,
                           capture_output=True)
            subprocess.run(
                ["git", "commit", "-m",
                 f"state: portfolio update {date.today().isoformat()}"],
                check=True, capture_output=True
            )
            subprocess.run(["git", "push"], check=True, capture_output=True)
            log.debug("Portfolio sincronizado com GitHub")
        except subprocess.CalledProcessError:
            log.debug("Git push skipped (sem alterações ou sem remote)")

    # ── POSIÇÕES ─────────────────────────────────────────────────

    def add_position(self, pos: Position):
        self.positions[pos.ticker] = pos
        self.save()
        log.info(f"Posição adicionada: {pos.ticker} {pos.strikes_label}")

    def close_position(self, ticker: str, close_price: float,
                       reason: str = "roll") -> float:
        if ticker not in self.positions:
            log.warning(f"Posição {ticker} não encontrada")
            return 0.0

        pos = self.positions.pop(ticker)
        pnl = (pos.net_credit - close_price) * 100 * pos.contracts

        entry = HistoryEntry(
            ticker       = ticker,
            strategy     = pos.strategy,
            short_strike = pos.short_strike,
            long_strike  = pos.long_strike,
            expiry       = pos.expiry,
            opened_at    = pos.opened_at,
            closed_at    = date.today().isoformat(),
            net_credit   = pos.net_credit,
            close_price  = close_price,
            pnl          = round(pnl, 2),
            reason       = reason,
        )
        self.history.append(entry)
        self.save()

        log.info(f"Posição fechada: {ticker} | P&L ${pnl:+.0f} | {reason}")
        return pnl

    def mark_removing(self, ticker: str):
        """Marca para não renovar — expira normalmente."""
        if ticker in self.positions:
            self.positions[ticker].removing = True
            self.save()
            log.info(f"{ticker} marcado para não renovar")

    def unmark_removing(self, ticker: str):
        if ticker in self.positions:
            self.positions[ticker].removing = False
            self.save()

    # ── PROPRIEDADES ─────────────────────────────────────────────

    @property
    def active_positions(self) -> dict[str, Position]:
        return {k: v for k, v in self.positions.items() if not v.removing}

    @property
    def removing_positions(self) -> dict[str, Position]:
        return {k: v for k, v in self.positions.items() if v.removing}

    @property
    def weekly_premium(self) -> float:
        return sum(p.net_credit * 100 for p in self.active_positions.values())

    @property
    def total_premium_collected(self) -> float:
        hist = sum(h.net_credit * 100 for h in self.history)
        return hist + self.weekly_premium

    @property
    def total_pnl(self) -> float:
        return sum(h.pnl for h in self.history)

    def summary(self) -> dict:
        return {
            "active":            len(self.active_positions),
            "removing":          len(self.removing_positions),
            "weekly_premium":    round(self.weekly_premium, 2),
            "total_collected":   round(self.total_premium_collected, 2),
            "total_pnl":         round(self.total_pnl, 2),
            "positions":         {k: asdict(v) for k, v in self.positions.items()},
            "history_count":     len(self.history),
        }
