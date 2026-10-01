"""OPEX — extrae SOLO el Operador de Red (OR) de UNA acta en PDF. Puerto del PATRÓN de
extraerRatioDeCertificadoCalibracion (Codigo.gs línea 3174-3205), no de una función que ya
existiera para el OR — el motor original nunca resolvía el OR desde el acta.

Módulo puro, igual que acta_analyzer.py: recibe bytes de PDF, devuelve el OR o None. No
descarga nada, no decide cuál acta usar — eso es responsabilidad de operator_resolver.py.
"""

import base64
import json
import re

from core.data_sources.llm_client import AnthropicClient, contexto_llamada
from core.prompts.or_extraction_prompt import OR_EXTRACTION_PROMPT_V1

_MAX_TOKENS = 300  # igual que extraerRatioDeCertificadoCalibracion
_EFFORT = "low"
_PATRON_JSON = re.compile(r"\{[\s\S]*\}")


def extraer_or_desde_pdf(pdf_bytes: bytes, llm: AnthropicClient, co: str | None = None) -> str | None:
    body = llm.cuerpo_extraccion_puntual(
        OR_EXTRACTION_PROMPT_V1,
        [
            {
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(pdf_bytes).decode("ascii")},
            },
            {"type": "text", "text": "Extrae el Operador de Red (OR) de este documento."},
        ],
        max_tokens=_MAX_TOKENS,
        effort=_EFFORT,
    )

    try:
        with contexto_llamada(llm, co=co, tipo="operador"):
            texto = llm.enviar(body)
        match = _PATRON_JSON.search(texto)
        if not match:
            return None
        parseado = json.loads(match.group(0))
        return parseado.get("or") or None
    except Exception:  # noqa: BLE001 — igual que el original: un acta sin OR legible no debe tumbar el resto del análisis
        return None
