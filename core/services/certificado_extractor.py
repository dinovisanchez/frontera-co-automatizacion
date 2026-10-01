"""Lee un certificado de calibración de un TC/TP ya instalado (URL desde Metabase) y extrae
SOLO la relación de transformación certificada. Puerto de
extraerRatioDeCertificadoCalibracion (Codigo.gs líneas 3174-3205) — un certificado siempre
documenta la relación real, más confiable que adivinar la capacidad cuando Lovable ya avisó
que ese dato automático no es correcto.

Mismo patrón que or_extractor.py: pregunta puntual y barata (max_tokens=300, effort="low"),
no la extracción completa de 14 campos.
"""

import base64
import json
import re

import requests

from core.data_sources.llm_client import AnthropicClient, contexto_llamada

_MAX_TOKENS = 300
_EFFORT = "low"
_LIMITE_BYTES = 18 * 1024 * 1024
_PATRON_JSON = re.compile(r"\{[\s\S]*\}")

_SYSTEM_PROMPT = (
    'Eres un ingeniero eléctrico colombiano. Te doy un certificado de calibración de un '
    'transformador de corriente (TC) o de tensión/potencial (TP). Extrae SOLO la relación de '
    'transformación nominal certificada (ej. "200/5" para TC, o "13200/120" para TP) y la '
    'clase de exactitud si aparece (ej. "0.5S"). Responde EXCLUSIVAMENTE un JSON, sin texto '
    'adicional: {"relacion": "200/5" (o null si no aparece), "clase": "0.5S" (o null)}'
)


def extraer_ratio_de_certificado_calibracion(url: str | None, llm: AnthropicClient) -> dict | None:
    """{"relacion": str, "clase": str|None} o None si no se pudo leer/no la trae — nunca
    lanza, un certificado no disponible/no legible no debe tumbar el resto del análisis."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code != 200:
            return None
        contenido = resp.content
        if len(contenido) >= _LIMITE_BYTES or contenido[:4] != b"%PDF":
            return None

        body = llm.cuerpo_extraccion_puntual(
            _SYSTEM_PROMPT,
            [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(contenido).decode("ascii")}},
                {"type": "text", "text": "Extrae la relación de transformación certificada de este documento."},
            ],
            max_tokens=_MAX_TOKENS, effort=_EFFORT,
        )
        with contexto_llamada(llm, tipo="certificado"):
            texto = llm.enviar(body)
        match = _PATRON_JSON.search(texto)
        if not match:
            return None
        parsed = json.loads(match.group(0))
        return parsed if parsed.get("relacion") else None
    except Exception:  # noqa: BLE001 — certificado no disponible/no legible, no debe tumbar el análisis
        return None
