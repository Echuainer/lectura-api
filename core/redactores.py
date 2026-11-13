"""Proveedores de IA que redactan los informes, intercambiables (patrón Strategy).

`informes` solo conoce `Redactor`; elegir Claude o DeepSeek es cambiar `LECTURA_AI_PROVIDER` (claude por defecto)."""
import logging
import os
from dataclasses import dataclass
from typing import Protocol

import anthropic
import httpx

log = logging.getLogger("lectura.ai")
MODELOS_CLAUDE = {"alumno": "claude-haiku-5-5", "curso": "claude-sonnet-5-5"}
MODELO_DEEPSEEK = "deepseek-flash"


@dataclass
class Resultado:
    texto: str
    cortado: bool  # el modelo se quedó sin max_tokens
    modelo: str
    tokens_entrada: int | None = None
    tokens_salida: int | None = None


class Redactor(Protocol):
    def completar(self, rol: str, sistema: str, contenido: str, max_tokens: int) -> Resultado: ...


class RedactorClaude:
    def completar(self, rol, sistema, contenido, max_tokens):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("Falta ANTHROPIC_API_KEY en el archivo .env")
        modelo = MODELOS_CLAUDE[rol]
        r = anthropic.Anthropic().messages.create(
            model=modelo, max_tokens=max_tokens,
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": contenido}])
        uso = getattr(r, "usage", None)
        return Resultado("".join(b.text for b in r.content if b.type == "text"), r.stop_reason == "max_tokens", modelo,
                         getattr(uso, "input_tokens", None), getattr(uso, "output_tokens", None))


class RedactorDeepSeek:
    def completar(self, rol, sistema, contenido, max_tokens):
        clave = os.environ.get("DEEPSEEK_API_KEY")
        if not clave:
            raise RuntimeError("Falta DEEPSEEK_API_KEY")
        r = httpx.post(
            "https://api.deepseek.com/chat/completions", headers={"Authorization": f"Bearer {clave}"}, timeout=120,
            json={"model": MODELO_DEEPSEEK, "max_tokens": max_tokens,
                  "thinking": {"type": "disabled"},  # DeepSeek piensa por defecto: más lento y caro para un texto
                  "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": contenido}]})
        r.raise_for_status()
        d = r.json()
        eleccion, uso = d["choices"][0], d.get("usage", {})
        return Resultado(eleccion["message"]["content"], eleccion.get("finish_reason") == "length", MODELO_DEEPSEEK,
                         uso.get("prompt_tokens"), uso.get("completion_tokens"))


REDACTORES: dict[str, type] = {"claude": RedactorClaude, "deepseek": RedactorDeepSeek}


ALIAS = {"anthropic": "claude"}  # the platform's IA_PROVIDER calls Claude "anthropic"


def redactor(institucion: str | None = None) -> Redactor:
    """The school's IA_PROVIDER (set in the platform) wins; without it, LECTURA_AI_PROVIDER; without that, Claude.
    A school value this service does not implement (the platform also knows "kimi") falls back to the default."""
    nombre = (institucion or "").strip().lower()
    nombre = ALIAS.get(nombre, nombre)
    if nombre not in REDACTORES:
        if nombre:
            log.warning("IA_PROVIDER de la institución no soportado aquí: %r", nombre)
        nombre = os.environ.get("LECTURA_AI_PROVIDER", "claude").strip().lower()
        nombre = ALIAS.get(nombre, nombre)
    if nombre not in REDACTORES:
        raise RuntimeError(f"LECTURA_AI_PROVIDER desconocido: {nombre!r} (usa {' o '.join(REDACTORES)})")
    return REDACTORES[nombre]()
