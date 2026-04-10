"""
analysis.py — Decisões de estratégia via LLM.
Usa llm_client.py — funciona com Gemini e Claude sem alterações.
"""

import json, logging
from datetime import date
from dataclasses import dataclass
from llm_client import ask, ask_text
from data import get_implied_volatility

log = logging.getLogger(__name__)

# ── PROMPTS ───────────────────────────────────────────────────────

STRATEGY_SYSTEM = """
És um gestor de portfolio especializado em covered calls e bear call spreads
em ações tech americanas. O teu estilo é conservador e disciplinado.

Regras de decisão:
- IV < 40%  → covered_call simples (spread não compensa)
- IV 40-70% → bear_call_spread (IV alta justifica o custo)
- IV > 70%  → bear_call_spread obrigatório com strike mais afastado

Responde SEMPRE em JSON válido. Sem texto extra. Sem markdown.
"""

RESEARCH_SYSTEM = """
És um analista de mercado sénior especializado em ações tech americanas.
Identificas oportunidades de covered call e bear call spread com base em
fundamentos, momentum, earnings e contexto macro.
Responde SEMPRE em JSON válido. Sem texto extra. Sem markdown.
"""

# ── STRATEGY DECISION ─────────────────────────────────────────────

@dataclass
class StrategyDecision:
    ticker:    str
    strategy:  str    # "covered_call" ou "bear_call_spread"
    iv:        float
    iv_rank:   float
    reasoning: str


def select_strategy(ticker: str, config) -> StrategyDecision:
    """
    Decide estratégia com base na IV.
    Respeita strategy_override se configurado.
    """
    # Override manual
    if config.strategy_override != "auto":
        iv, iv_rank = get_implied_volatility(ticker)
        return StrategyDecision(
            ticker    = ticker,
            strategy  = config.strategy_override,
            iv        = iv,
            iv_rank   = iv_rank,
            reasoning = f"Override manual: {config.strategy_override}",
        )

    iv, iv_rank = get_implied_volatility(ticker)

    prompt = f"""
Ticker: {ticker}
IV atual (HV anual): {iv:.1%}
IV Rank (0-100): {iv_rank:.0f}
Config target_otm_pct: {config.target_otm_pct:.1%}
Config spread_width: ${config.spread_width}
Config min_premium: ${config.min_premium}

Com base na IV, decide a estratégia para esta semana.

Responde com este JSON:
{{
    "strategy": "covered_call" ou "bear_call_spread",
    "reasoning": "explicação em 1 frase",
    "suggested_otm_pct": 0.02,
    "suggested_spread_width": 5.0
}}
"""

    try:
        result = ask(prompt, system=STRATEGY_SYSTEM)
        strategy = result.get("strategy", "covered_call")

        # Aplicar sugestões do LLM ao config
        if "suggested_otm_pct" in result:
            config.target_otm_pct = result["suggested_otm_pct"]
        if "suggested_spread_width" in result:
            config.spread_width = result["suggested_spread_width"]

        log.info(
            f"{ticker} | IV: {iv:.0%} | Rank: {iv_rank:.0f} | "
            f"→ {strategy} | {result.get('reasoning','')}"
        )

        return StrategyDecision(
            ticker    = ticker,
            strategy  = strategy,
            iv        = iv,
            iv_rank   = iv_rank,
            reasoning = result.get("reasoning", ""),
        )
    except Exception as e:
        log.warning(f"{ticker}: erro na decisão LLM ({e}) — usando regra simples")
        # Fallback: regra determinística sem LLM
        strategy = "bear_call_spread" if iv >= 0.40 else "covered_call"
        return StrategyDecision(ticker=ticker, strategy=strategy,
                                iv=iv, iv_rank=iv_rank,
                                reasoning="Fallback: regra IV")


# ── DAILY RESEARCH ────────────────────────────────────────────────

def run_evening_analysis(market: dict, movers: dict,
                          portfolio_tickers: list[str]) -> dict:
    """Análise após fecho — identifica oportunidades para amanhã."""

    prompt = f"""
Data: {date.today().strftime('%d de %B de %Y')}

MERCADO HOJE:
{json.dumps(market, indent=2)}

MAIORES MOVIMENTOS:
{json.dumps(movers, indent=2)}

PORTFOLIO ATUAL: {portfolio_tickers}

Analisa o mercado e identifica 3-5 ações interessantes para
covered call ou bear call spread na próxima semana.

Responde com este JSON:
{{
    "opportunities": [
        {{
            "ticker": "AAPL",
            "name": "Apple Inc",
            "direction": "bullish" | "bearish" | "neutral",
            "suggested_strategy": "covered_call" | "bear_call_spread",
            "thesis": "explicação em 2-3 frases",
            "catalysts": ["catalisador 1", "catalisador 2"],
            "risks": ["risco 1"],
            "confidence": 0-100,
            "urgency": "alta" | "média" | "baixa",
            "time_horizon": "esta semana" | "próximas 2 semanas"
        }}
    ],
    "market_summary": "resumo do dia em 2 frases",
    "macro_note": "contexto macro relevante",
    "vix_note": "interpretação do VIX atual"
}}
"""

    try:
        return ask(prompt, system=RESEARCH_SYSTEM, max_tokens=2000)
    except Exception as e:
        log.error(f"Erro no research: {e}")
        return {"opportunities": [], "market_summary": "Erro na análise", "macro_note": ""}


def run_premarket_analysis(premarket: dict, futures: dict,
                            evening_analysis: dict) -> dict:
    """Briefing pré-abertura — atualiza análise com dados frescos."""

    prompt = f"""
São 08h30 ET. Mercado abre em 1 hora.

PRE-MARKET SPY:
{json.dumps(premarket, indent=2)}

FUTUROS ES:
{json.dumps(futures, indent=2)}

ANÁLISE DA VÉSPERA (resumo):
{evening_analysis.get('market_summary', 'N/A')}

Com base nos dados de pre-market, atualiza o briefing.

Responde com este JSON:
{{
    "gap_analysis": "interpretação do gap",
    "market_bias": "bullish" | "bearish" | "neutral",
    "macro_risk": "alto" | "médio" | "baixo",
    "summary": "briefing em 2 frases para notificação",
    "action_items": ["item 1", "item 2"]
}}
"""

    try:
        return ask(prompt, system=RESEARCH_SYSTEM, max_tokens=600)
    except Exception as e:
        log.error(f"Erro no premarket: {e}")
        return {"summary": "Erro na análise", "market_bias": "neutral"}
