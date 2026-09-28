"""Wrapper de la API de Anthropic — puerto de llamarClaudeDiagrama (Codigo.gs línea 1608).

Transporte genérico: arma la petición HTTP tal cual el original (mismo endpoint, mismos
headers) y devuelve el texto concatenado de los bloques `type: "text"` de la respuesta. La
construcción del `body` (qué modelo/system/mensajes exactos) vive en cada servicio que lo
usa (ej. acta_analyzer.py), no acá — este módulo no sabe nada de actas ni de CAPEX/OPEX.

A diferencia del original, SÍ tiene retry con backoff (requisito nuevo del proyecto migrado
— Codigo.gs no lo tenía, lanzaba error a la primera falla).
"""

import time

import requests

from config.settings import AnthropicConfig

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_REINTENTOS = 2
BACKOFF_BASE_SEG = 2.0
# TODO el backend corre bajo maxDuration=60s de Vercel (vercel.json) — un TIMEOUT_SEG de 120s
# por intento (Dinovi, 2026-09-28: CO0200000687 se quedó reintentando "para siempre" en
# Comparación Masiva) permitía que UN SOLO intento colgado ya superara el límite del propio
# Vercel, que entonces mata el proceso a la fuerza SIN que este código alcance a capturar la
# excepción ni a registrar nada — el siguiente reintento del frontend choca con lo mismo,
# ciclo infinito con cero avance. 25s por intento x máx. 2 intentos (con el backoff de abajo)
# ≈ 52s en el peor caso, deja margen real dentro de los 60s para el resto del paso (descarga,
# OCR, escritura a Sheets) y para que la excepción SÍ se capture y quede en observaciones.
TIMEOUT_SEG = 25


class AnthropicAuthError(RuntimeError):
    """401/403 — API key inválida. Error crítico, no se reintenta."""


class AnthropicRateLimitError(RuntimeError):
    """429 tras agotar los reintentos — para que el llamador decida (ej. reprogramar el job)."""


class AnthropicClient:
    def __init__(self, cfg: AnthropicConfig):
        self._cfg = cfg

    def enviar(self, body: dict) -> str:
        """Envía `body` tal cual (ya debe traer model/max_tokens/output_config/system/messages)
        y devuelve el texto de la respuesta — equivalente a llamarClaudeDiagrama().
        """
        headers = {
            "x-api-key": self._cfg.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        ultimo_error: Exception | None = None

        for intento in range(1, MAX_REINTENTOS + 1):
            try:
                resp = requests.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=body, timeout=TIMEOUT_SEG)
            except requests.RequestException as e:
                ultimo_error = e
                if intento < MAX_REINTENTOS:
                    time.sleep(BACKOFF_BASE_SEG * (2 ** (intento - 1)))
                continue

            if resp.status_code == 200:
                data = resp.json()
                return "\n".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")

            if resp.status_code in (401, 403):
                raise AnthropicAuthError(f"Claude respondió HTTP {resp.status_code}: {resp.text[:500]}")

            if resp.status_code == 429 or resp.status_code >= 500:
                ultimo_error = AnthropicRateLimitError(
                    f"Claude respondió HTTP {resp.status_code}: {resp.text[:500]}"
                )
                if intento < MAX_REINTENTOS:
                    time.sleep(BACKOFF_BASE_SEG * (2 ** (intento - 1)))
                continue

            raise RuntimeError(f"Claude respondió HTTP {resp.status_code}: {resp.text[:500]}")

        raise ultimo_error or RuntimeError("Claude: fallo desconocido tras reintentos.")

    def cuerpo_extraccion_acta(self, system_prompt: str, contenido_mensaje: list[dict]) -> dict:
        """Arma el body con los parámetros EXACTOS de bodyClaudeActa/bodyClaudeActaTexto
        (Codigo.gs líneas 3395-3422): model/max_tokens/output_config del acta original, sin
        cambiar ninguno por defecto.

        `system_prompt` (ACTA_EXTRACTION_PROMPT_V2, ~2500 tokens) es idéntico en cada llamada
        de un mismo job — hasta 5 actas por CO, cada una con su propio intento texto+PDF — así
        que va con `cache_control: ephemeral` para que Anthropic lo facture como cache-hit
        (~90% más barato) en vez de reprocesarlo entero cada vez.
        """
        return {
            "model": self._cfg.model,
            "max_tokens": self._cfg.max_tokens,
            "output_config": {"effort": self._cfg.effort},
            "system": [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": contenido_mensaje}],
        }

    def cuerpo_extraccion_puntual(
        self, system_prompt: str, contenido_mensaje: list[dict], max_tokens: int, effort: str
    ) -> dict:
        """Para preguntas puntuales y baratas sobre UN documento (ej. el OR de una acta, o la
        relación certificada de un TC/TP) — mismo patrón que
        extraerRatioDeCertificadoCalibracion (Codigo.gs línea 3174-3205): max_tokens/effort
        bajos, no los de la extracción completa de 14 campos.

        `cache_control` acá también: estos prompts son cortos y normalmente quedan bajo el
        mínimo cacheable, así que Anthropic simplemente lo ignora sin costo — no hace daño
        dejarlo por si el prompt crece.
        """
        return {
            "model": self._cfg.model,
            "max_tokens": max_tokens,
            "output_config": {"effort": effort},
            "system": [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": contenido_mensaje}],
        }


def get_llm_client(cfg: AnthropicConfig) -> AnthropicClient:
    return AnthropicClient(cfg)
