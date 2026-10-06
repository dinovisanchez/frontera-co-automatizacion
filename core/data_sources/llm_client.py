"""Wrapper de la API de Anthropic — puerto de llamarClaudeDiagrama (Codigo.gs línea 1608).

Transporte genérico: arma la petición HTTP tal cual el original (mismo endpoint, mismos
headers) y devuelve el texto concatenado de los bloques `type: "text"` de la respuesta. La
construcción del `body` (qué modelo/system/mensajes exactos) vive en cada servicio que lo
usa (ej. acta_analyzer.py), no acá — este módulo no sabe nada de actas ni de CAPEX/OPEX.

A diferencia del original, SÍ tiene retry con backoff (requisito nuevo del proyecto migrado
— Codigo.gs no lo tenía, lanzaba error a la primera falla).
"""

import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable

import requests

from config.settings import AnthropicConfig

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_REINTENTOS = 3
BACKOFF_BASE_SEG = 2.0
# TODO el backend corre bajo maxDuration=60s de Vercel (vercel.json) — un TIMEOUT_SEG de 120s
# por intento (Dinovi, 2026-09-28: CO0200000687 se quedó reintentando "para siempre" en
# Comparación Masiva) permitía que UN SOLO intento colgado ya superara el límite del propio
# Vercel, que entonces mata el proceso a la fuerza SIN que este código alcance a capturar la
# excepción ni a registrar nada — el siguiente reintento del frontend choca con lo mismo,
# ciclo infinito con cero avance. 15s por intento x máx. 3 intentos (con el backoff de abajo)
# ≈ 51s en el peor caso: mismo presupuesto total que antes (2x25s+2s≈52s) pero con UN intento
# más para absorber un 503 pasajero de Claude (Dinovi, 2026-09-29: incidente real de ~35 min
# con "Claude respondió HTTP 503" en cada llamada de actas) sin gastar más tiempo total ni
# arriesgar el timeout de 60s si un intento se cuelga en vez de fallar rápido.
TIMEOUT_SEG = 15


class AnthropicAuthError(RuntimeError):
    """401/403 — API key inválida. Error crítico, no se reintenta."""


class AnthropicRateLimitError(RuntimeError):
    """429 tras agotar los reintentos — para que el llamador decida (ej. reprogramar el job)."""


@contextmanager
def contexto_llamada(llm, **etiquetas):
    """Etiqueta (co, tipo de llamada, acta…) las llamadas que se hagan dentro del bloque, para que el
    registro de consumo sepa a qué corresponden. Funciona con cualquier objeto que tenga el atributo
    `contexto` (el AnthropicClient real y sus subclases de prueba) y no hace nada con el resto."""
    anterior = getattr(llm, "contexto", None)
    if anterior is None:
        yield
        return
    llm.contexto = {**anterior, **{k: v for k, v in etiquetas.items() if v is not None}}
    try:
        yield
    finally:
        llm.contexto = anterior


class AnthropicClient:
    def __init__(self, cfg: AnthropicConfig):
        self._cfg = cfg
        # Registro de consumo (core/services/consumo.py): wiring.py conecta `registrador` a la hoja
        # "PyConsumo". Es opcional y NUNCA debe romper una llamada (ver _registrar).
        self.registrador: Callable[[dict], None] | None = None
        self.contexto: dict = {}
        # Por defecto los de producción (ver los comentarios de TIMEOUT_SEG). La herramienta de
        # comparación los ajusta al tiempo que le queda dentro de los 60 s de Vercel.
        self.timeout_seg: float = TIMEOUT_SEG
        self.max_reintentos: int = MAX_REINTENTOS

    def _registrar(self, body: dict, inicio: float, intentos: int, fallidos: int, resultado: str, **extra) -> None:
        if self.registrador is None:
            return
        try:
            contenido = (body.get("messages") or [{}])[-1].get("content") or []
            tiene_pdf = isinstance(contenido, list) and any(b.get("type") == "document" for b in contenido if isinstance(b, dict))
            registro = {
                "fecha_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "co": self.contexto.get("co"),
                "tipo": self.contexto.get("tipo") or ("pdf" if tiene_pdf else "texto"),
                "origen": self.contexto.get("origen") or "individual",
                "acta": self.contexto.get("acta"),
                "modelo": body.get("model"),
                "esfuerzo": (body.get("output_config") or {}).get("effort"),
                "intentos": intentos, "fallidos": fallidos, "segundos": round(time.monotonic() - inicio, 2),
                "resultado": resultado,
            }
            registro.update(extra)
            self.registrador(registro)
        except Exception as e:  # noqa: BLE001 — medir nunca debe romper la extracción
            print(f"[consumo] fallo al registrar: {e}", file=sys.stderr)

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
        inicio = time.monotonic()
        fallidos = 0  # intentos que no devolvieron 200 (un timeout del cliente puede cobrarse igual)

        for intento in range(1, self.max_reintentos + 1):
            try:
                resp = requests.post(ANTHROPIC_MESSAGES_URL, headers=headers, json=body, timeout=self.timeout_seg)
            except requests.RequestException as e:
                ultimo_error = e
                fallidos += 1
                if intento < self.max_reintentos:
                    time.sleep(BACKOFF_BASE_SEG * (2 ** (intento - 1)))
                continue

            if resp.status_code == 200:
                data = resp.json()
                uso = data.get("usage") or {}
                self._registrar(
                    body, inicio, intento, fallidos, "ok",
                    entrada=uso.get("input_tokens"), escritura_cache=uso.get("cache_creation_input_tokens"),
                    lectura_cache=uso.get("cache_read_input_tokens"), salida=uso.get("output_tokens"),
                    razonamiento=(uso.get("output_tokens_details") or {}).get("thinking_tokens"),
                    stop_reason=data.get("stop_reason"), request_id=resp.headers.get("request-id"),
                )
                return "\n".join(b["text"] for b in data.get("content", []) if b.get("type") == "text")

            if resp.status_code in (401, 403):
                self._registrar(body, inicio, intento, fallidos + 1, "error", error=f"HTTP {resp.status_code}", request_id=resp.headers.get("request-id"))
                raise AnthropicAuthError(f"Claude respondió HTTP {resp.status_code}: {resp.text[:500]}")

            if resp.status_code == 429 or resp.status_code >= 500:
                ultimo_error = AnthropicRateLimitError(
                    f"Claude respondió HTTP {resp.status_code}: {resp.text[:500]}"
                )
                fallidos += 1
                if intento < self.max_reintentos:
                    time.sleep(BACKOFF_BASE_SEG * (2 ** (intento - 1)))
                continue

            self._registrar(body, inicio, intento, fallidos + 1, "error", error=f"HTTP {resp.status_code}", request_id=resp.headers.get("request-id"))
            raise RuntimeError(f"Claude respondió HTTP {resp.status_code}: {resp.text[:500]}")

        self._registrar(
            body, inicio, self.max_reintentos, fallidos, "error",
            error=type(ultimo_error).__name__ if ultimo_error else "desconocido",
        )
        raise ultimo_error or RuntimeError("Claude: fallo desconocido tras reintentos.")

    def cuerpo_extraccion_acta(self, system_prompt: str, contenido_mensaje: list[dict]) -> dict:
        """Arma el body con los parámetros EXACTOS de bodyClaudeActa/bodyClaudeActaTexto
        (Codigo.gs líneas 3395-3422): model/max_tokens/output_config del acta original, sin
        cambiar ninguno por defecto.

        `system_prompt` (ACTA_EXTRACTION_PROMPT_V2/V3, ~2500 tokens) es idéntico en cada llamada
        de un mismo job — (antes hasta 5 actas por CO; hoy UNA, ver alcance_combiner.seleccionar_acta) — así
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

    def cuerpo_extraccion_acta_texto(self, system_prompt: str, contenido_mensaje: list[dict]) -> dict:
        """Igual que `cuerpo_extraccion_acta`, pero con el modelo/esfuerzo de la lectura por TEXTO
        (`model_acta_texto` / `effort_acta_texto`, hoy Sonnet 5.5): es la llamada más frecuente y se
        decide aparte de la lectura por PDF, el operador de red y los certificados."""
        body = self.cuerpo_extraccion_acta(system_prompt, contenido_mensaje)
        body["model"] = self._cfg.model_acta_texto
        body["output_config"] = {"effort": self._cfg.effort_acta_texto}
        return body

    def cuerpo_extraccion_puntual_texto(self, system_prompt: str, contenido_mensaje: list[dict], max_tokens: int) -> dict:
        """Pregunta puntual sobre el TEXTO ya extraído de un documento (no sobre el PDF): usa el modelo y el
        esfuerzo de la lectura de actas por texto (`model_acta_texto` / `effort_acta_texto`, hoy Sonnet 5.5 ·
        medio) — el mismo que ya está probado con ese modelo — en vez de Opus. `max_tokens` holgado: el
        razonamiento también cuenta como salida y, si se corta, no llega la respuesta."""
        body = self.cuerpo_extraccion_puntual(system_prompt, contenido_mensaje, max_tokens=max_tokens, effort=self._cfg.effort_acta_texto)
        body["model"] = self._cfg.model_acta_texto
        return body

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
