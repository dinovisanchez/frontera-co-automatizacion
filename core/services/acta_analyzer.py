"""CAPEX — analiza UNA acta y devuelve sus 14 campos. Puerto de bodyClaudeActa /
bodyClaudeActaTexto (Codigo.gs líneas 3395-3422).

Módulo PURO a propósito (requisito del proyecto): no descarga nada, no decide si hace falta
otra acta, no combina resultados entre actas — eso es responsabilidad de alcance_combiner.py.
Solo sabe convertir (texto OCR | bytes de PDF) + metadatos de la visita en el JSON de 14
campos, vía el LLM.
"""

import base64
from dataclasses import dataclass

from core.data_sources.llm_client import AnthropicClient
from core.prompts.acta_extraction_prompt import ACTA_EXTRACTION_PROMPT_V1
from core.validators.alcance_schema import RespuestaActa, normalizar_spec_acta, parsear_respuesta_alcance


@dataclass
class MetadatosActa:
    co: str
    tipo_acta: str  # service_type_id: VIPE/INFR/NOTE/INST/...
    fecha_visita: str


def _instruccion_comun(meta: MetadatosActa) -> str:
    return (
        f"Extrae SOLO lo que esta acta puntual traiga (medidor, transformador, TC/TP, "
        f"ubicación) — deja en null lo que no mencione, no lo inventes."
        f" [{meta.tipo_acta}, {meta.fecha_visita}, frontera {meta.co}]"
    )


def analizar_acta_desde_texto(meta: MetadatosActa, texto_ocr: str, llm: AnthropicClient) -> RespuestaActa:
    """Puerto de bodyClaudeActaTexto — intento rápido, SOLO texto (OCR), sin imágenes."""
    instruccion = (
        "Adjunto el TEXTO (extraído por OCR, puede tener errores de reconocimiento — si algo "
        "queda ilegible o ambiguo, prefiere dejarlo en null antes que adivinar) del acta de "
        f"visita ({meta.tipo_acta}, {meta.fecha_visita}) de la frontera {meta.co}. "
        + _instruccion_comun(meta)
        + f"\n\n--- TEXTO DEL ACTA (OCR) ---\n{texto_ocr}"
    )
    body = llm.cuerpo_extraccion_acta(
        ACTA_EXTRACTION_PROMPT_V1,
        [{"type": "text", "text": instruccion}],
    )
    return _ejecutar(body, llm)


def analizar_acta_desde_pdf(meta: MetadatosActa, pdf_bytes: bytes, llm: AnthropicClient) -> RespuestaActa:
    """Puerto de bodyClaudeActa — modo con imágenes (PDF completo), fallback cuando el texto
    no trajo todos los campos que hacían falta.
    """
    instruccion = (
        f"Adjunto el acta de visita ({meta.tipo_acta}, {meta.fecha_visita}) de la frontera "
        f"{meta.co}. " + _instruccion_comun(meta)
    )
    body = llm.cuerpo_extraccion_acta(
        ACTA_EXTRACTION_PROMPT_V1,
        [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(pdf_bytes).decode("ascii"),
                },
            },
            {"type": "text", "text": instruccion},
        ],
    )
    return _ejecutar(body, llm)


def _ejecutar(body: dict, llm: AnthropicClient) -> RespuestaActa:
    texto_respuesta = llm.enviar(body)
    resultado = parsear_respuesta_alcance(texto_respuesta)
    if resultado.spec is not None:
        resultado.spec = normalizar_spec_acta(resultado.spec)
    return resultado
