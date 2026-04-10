"""
llm_client.py — Interface única para Gemini e Claude.
Para trocar de provider: mudar LLM_PROVIDER no Railway.
Zero alterações no restante código.
"""

import os, json, logging
from config import LLM_PROVIDER, LLM_MODEL, GEMINI_API_KEY

log = logging.getLogger(__name__)


def ask(prompt: str, system: str = "", max_tokens: int = 800) -> dict:
    """
    Chama o LLM configurado e devolve sempre um dict (JSON parseado).
    Funciona com Gemini e Claude sem alterar o código que chama esta função.
    """
    raw = _call_llm(prompt, system, max_tokens)
    return _parse_json(raw)


def ask_text(prompt: str, system: str = "", max_tokens: int = 2000) -> str:
    """Igual ao ask() mas devolve texto simples (para research)."""
    return _call_llm(prompt, system, max_tokens)


def _call_llm(prompt: str, system: str, max_tokens: int) -> str:
    """Despacha para o provider correto."""
    if LLM_PROVIDER == "gemini":
        return _call_gemini(prompt, system, max_tokens)
    elif LLM_PROVIDER == "claude":
        return _call_claude(prompt, system, max_tokens)
    else:
        raise ValueError(f"LLM_PROVIDER desconhecido: {LLM_PROVIDER}")


def _call_gemini(prompt: str, system: str, max_tokens: int) -> str:
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    model    = genai.GenerativeModel(LLM_MODEL)
    response = model.generate_content(
        full_prompt,
        generation_config={"max_output_tokens": max_tokens}
    )
    log.debug(f"Gemini ({LLM_MODEL}) respondeu")
    return response.text.strip()


def _call_claude(prompt: str, system: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic()
    kwargs = dict(
        model      = LLM_MODEL,
        max_tokens = max_tokens,
        messages   = [{"role": "user", "content": prompt}]
    )
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    log.debug(f"Claude ({LLM_MODEL}) respondeu")
    return response.content[0].text.strip()


def _parse_json(text: str) -> dict:
    """Remove markdown code fences e parseia JSON."""
    # Gemini às vezes devolve ```json ... ```
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            if part.startswith("json"):
                text = part[4:].strip()
                break
            elif part.strip().startswith("{"):
                text = part.strip()
                break
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        log.error(f"Erro a parsear JSON: {e}\nTexto: {text[:200]}")
        return {"error": str(e), "raw": text}
